"""Наполнение каталога стартовым списком.

Общепринятого рейтинга у книг нет — ни аналога топ-250, ни честной выдачи
«самого популярного»: то, что чаще покупают, для литклуба слабый ориентир.
Поэтому список курируемый (app/seed/books.py), а данные к нему подтягиваются
из тех же источников, что и при обычном поиске, — с обложками, ISBN,
описаниями и мировыми оценками.

Ищем структурным запросом «автор + название»: свободная строка вроде
«Дюна Герберт» приносит биографии и путеводители вперёд самой книги.

Запуск:  ./venv/bin/python -m app.import_books
         ./venv/bin/python -m app.import_books --limit 20 --dry-run
"""

import argparse
import asyncio
import logging

import httpx

from app.db import SessionLocal
from app.seed.books import SEED
from app.services.books import google_books, merge, open_library
from app.services.books.normalize import BookCandidate, norm

logger = logging.getLogger("import_books")

# Пауза между книгами: у Google Books дневная квота, и упереться в неё на
# двухсотой книге обиднее, чем подождать лишнюю минуту.
DELAY_SECONDS = 0.4


def matches(candidate: BookCandidate, title: str, author: str) -> bool:
    """Похож ли найденный кандидат на то, что искали.

    Источники охотно подсовывают «Всё о Дюне» и «Толкин: биография» — берём
    только то, где название совпадает по существу, а автор упомянут.
    """
    wanted, found = norm(title), norm(candidate.title)
    if not (found.startswith(wanted) or wanted.startswith(found)):
        return False
    # Фамилия автора — последнее слово; она надёжнее полного имени, которое
    # у источников записано то с отчеством, то инициалами, то по-английски.
    surname = norm(author).split()[-1]
    return any(surname in norm(name) for name in candidate.authors)


async def find(client: httpx.AsyncClient, title: str, author: str) -> BookCandidate | None:
    results = await asyncio.gather(
        google_books.search(client, f'intitle:"{title}" inauthor:"{author}"', 10),
        open_library.search(client, f'title:"{title}" author:"{author}"', 10),
        return_exceptions=True,
    )
    groups = [r for r in results if not isinstance(r, BaseException)]
    if not groups:
        return None

    merged = merge.dedupe(groups)
    # Точное совпадение важнее популярности: иначе первым уедет сборник
    # или биография писателя.
    exact = [c for c in merged if matches(c, title, author)]
    if not exact:
        return None

    # Берём первого — порядок задан приоритетом источников, и у Google Books
    # названия чище: Open Library любит писать «Война и мир / Voĭna i mir».
    best = exact[0]
    # А вот известность добираем у остальных: это та же книга, просто
    # издания разошлись по ISBN и не склеились автоматически.
    for other in exact[1:]:
        if (other.world_ratings_count or 0) > (best.world_ratings_count or 0):
            best.world_rating = other.world_rating
            best.world_ratings_count = other.world_ratings_count
    return best


async def run(limit: int | None, dry_run: bool) -> None:
    books = SEED[:limit] if limit else SEED
    client = merge.get_client()

    added = existing = missed = 0
    for index, (author, title) in enumerate(books, start=1):
        try:
            candidate = await find(client, title, author)
        except Exception as exc:  # источник ответил неожиданным
            logger.warning("%s — %s: источник сбоит (%s)", author, title, exc)
            candidate = None

        if candidate is None:
            missed += 1
            logger.info("[%3d/%d] ✗ не нашли: %s — %s", index, len(books), author, title)
            await asyncio.sleep(DELAY_SECONDS)
            continue

        if dry_run:
            logger.info(
                "[%3d/%d] → %s — %s (оценок в мире: %s)",
                index, len(books), ", ".join(candidate.authors[:2]),
                candidate.title, candidate.world_ratings_count or 0,
            )
            await asyncio.sleep(DELAY_SECONDS)
            continue

        async with SessionLocal() as session:
            before = await merge.find_existing(session, candidate)
            book = await merge.ensure_book(session, candidate)
            await session.commit()
            if before is None:
                added += 1
                logger.info("[%3d/%d] + %s", index, len(books), book.title)
            else:
                existing += 1

        await asyncio.sleep(DELAY_SECONDS)

    await merge.aclose()
    logger.info(
        "Готово: добавлено %d, уже было %d, не нашлось %d из %d",
        added, existing, missed, len(books),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Наполнить каталог стартовым списком")
    parser.add_argument("--limit", type=int, default=None, help="сколько книг из списка взять")
    parser.add_argument("--dry-run", action="store_true", help="только показать, что нашлось")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    # httpx рассказывает про каждый запрос — на двухстах книгах это четыреста
    # строк, в которых тонет то, ради чего скрипт запускали.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    asyncio.run(run(args.limit, args.dry_run))


if __name__ == "__main__":
    main()
