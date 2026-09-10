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
import sqlalchemy as sa

from app.db import SessionLocal
from app.models import Book, BookSource
from app.seed.books import SEED
from app.services.books import google_books, merge, open_library
from app.services.books.normalize import BookCandidate, dedup_key, norm

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


async def attempt(
    client: httpx.AsyncClient, google_query: str, openlib_query: str, title: str, author: str
) -> BookCandidate | None:
    results = await asyncio.gather(
        google_books.search(client, google_query, 10),
        open_library.search(client, openlib_query, 10),
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


async def find(client: httpx.AsyncClient, title: str, author: str) -> BookCandidate | None:
    """Сначала точный запрос по полям, потом обычный.

    Структурный поиск (`intitle:` / `title:`) точнее, но на русских названиях
    источники нередко не находят по нему вообще ничего. Свободная строка
    находит, зато тащит биографии и путеводители — их отсекает та же проверка
    совпадения, что и в первом проходе.
    """
    found = await attempt(
        client,
        f'intitle:"{title}" inauthor:"{author}"',
        f'title:"{title}" author:"{author}"',
        title,
        author,
    )
    if found is not None:
        return found

    plain = f"{title} {author}"
    return await attempt(client, plain, plain, title, author)


async def retitle() -> tuple[int, int]:
    """Приводит названия и авторов уже заведённых книг к выверенному списку.

    Отдельный проход, потому что первые прогоны сохраняли то, что отдал
    источник. Сети не требует: сопоставляем по нормализованному названию,
    той же меркой, что и при поиске.

    Попутно вскрываются дубли: одна книга, заведённая дважды под разными
    написаниями автора, после приведения к списку получает один и тот же
    ключ. Лишнюю запись убираем, перевесив на оставшуюся привязки к
    источникам, — но только если с ней никто ничего не делал.
    """
    fixed = merged = 0
    async with SessionLocal() as session:
        books = list((await session.execute(sa.select(Book))).scalars().all())
        by_id = {book.id: book for book in books}

        for author, title in SEED:
            wanted = norm(title)
            surname = norm(author).split()[-1]
            found = [
                book
                for book in books
                if book.id in by_id
                and norm(book.title).startswith(wanted)
                and any(surname in norm(name) for name in (book.authors or []))
            ]
            if not found:
                continue

            keeper, *duplicates = found
            key = dedup_key(title, [author])

            for extra in duplicates:
                if await has_traces(session, extra.id):
                    logger.info(
                        "! дубль «%s» оставлен: с ним уже работали", extra.title
                    )
                    continue
                await session.execute(
                    sa.update(BookSource)
                    .where(BookSource.book_id == extra.id)
                    .values(book_id=keeper.id)
                )
                await session.delete(extra)
                by_id.pop(extra.id, None)
                merged += 1
                logger.info("− склеен дубль: %s", extra.title)

            if keeper.title == title and (keeper.authors or [None])[0] == author:
                continue

            keeper.title = title
            keeper.authors = [author]
            keeper.dedup_key = key
            fixed += 1
            logger.info("~ %s — %s", author, title)
            # Пишем сразу: столкновение ключей должно всплыть на своей книге,
            # а не обрушить весь проход в самом конце.
            await session.flush()

        await session.commit()
    return fixed, merged


async def has_traces(session, book_id: int) -> bool:
    """Есть ли у книги следы человеческой работы — отметки, спрос, встречи."""
    for table, column in (
        ("reading_entries", "book_id"),
        ("demands", "book_id"),
        ("events", "book_id"),
        ("organizer_applications", "book_id"),
    ):
        count = (
            await session.execute(
                sa.text(f"SELECT count(*) FROM {table} WHERE {column} = :id"), {"id": book_id}
            )
        ).scalar_one()
        if count:
            return True
    return False


async def run(limit: int | None, dry_run: bool, only_missing: bool) -> None:
    books = SEED[:limit] if limit else SEED

    if only_missing:
        # Пропускаем то, что уже заведено: у Google Books дневная квота, и
        # тратить её на повторный поиск известного незачем.
        async with SessionLocal() as session:
            known = set(
                (await session.execute(sa.select(Book.dedup_key))).scalars().all()
            )
        books = tuple(
            (author, title)
            for author, title in books
            if dedup_key(title, [author]) not in known
        )
        logger.info("К поиску осталось %d книг", len(books))

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

        # Название и автор берутся из выверенного списка, а не из источника:
        # оттуда приезжает «Метро 2033. Часть 3, 4» и «граф Лео Толстой».
        # Источник ценен обложкой, ISBN, описанием и годом — не подписью.
        candidate.title = title
        candidate.authors = [author, *[a for a in candidate.authors if norm(a) != norm(author)]]

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
    parser.add_argument(
        "--only-missing",
        action="store_true",
        help="искать только то, чего ещё нет в каталоге",
    )
    parser.add_argument(
        "--retitle",
        action="store_true",
        help="привести названия уже заведённых книг к списку, без обращений к сети",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    # httpx рассказывает про каждый запрос — на двухстах книгах это четыреста
    # строк, в которых тонет то, ради чего скрипт запускали.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    if args.retitle:
        fixed, merged = asyncio.run(retitle())
        logger.info("Поправлено книг: %d, склеено дублей: %d", fixed, merged)
        return
    asyncio.run(run(args.limit, args.dry_run, args.only_missing))


if __name__ == "__main__":
    main()
