"""Поиск по каталогу и двум внешним источникам со склейкой дублей.

Порядок кандидатов: сначала то, что уже в каталоге, затем Google Books, затем
Open Library. Совпавшие склеиваются в одну карточку, поля берутся у первого,
пустые добираются у следующего, — отсюда и приоритет Google Books.
"""

import asyncio
import logging

import httpx
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_config
from app.models import Book, BookSource
from app.models.enums import BookSourceKind, BookStatus
from app.services.books import google_books, open_library
from app.services.books.normalize import BookCandidate, dedup_key

logger = logging.getLogger(__name__)

_client: httpx.AsyncClient | None = None


def get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(
            timeout=get_config().books_search_timeout,
            headers={"User-Agent": "litclub-bot/0.1 (university book club)"},
            follow_redirects=True,
        )
    return _client


async def aclose() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


def book_to_candidate(book: Book) -> BookCandidate:
    return BookCandidate(
        source=BookSourceKind.MANUAL,
        external_id=str(book.id),
        title=book.title,
        authors=list(book.authors or []),
        year=book.year,
        cover_url=book.cover_url,
        description=book.description,
        page_count=book.page_count,
        isbn13=book.isbn13,
        language=book.language,
        genres=list(book.genres or []),
        world_rating=book.world_rating,
        world_ratings_count=book.world_ratings_count,
        book_id=book.id,
    )


def combine(base: BookCandidate, other: BookCandidate) -> BookCandidate:
    """Дополняет карточку данными второго источника, не перетирая заполненное."""
    # Известность берём у того источника, где голосов больше: у Google Books
    # и Open Library разный охват, и меньшее число просто хуже осведомлено.
    if (other.world_ratings_count or 0) > (base.world_ratings_count or 0):
        base.world_rating = other.world_rating
        base.world_ratings_count = other.world_ratings_count

    for attribute in ("year", "cover_url", "description", "page_count", "isbn13", "language"):
        if getattr(base, attribute) in (None, "") and getattr(other, attribute) not in (None, ""):
            setattr(base, attribute, getattr(other, attribute))
    if not base.genres and other.genres:
        base.genres = other.genres
    if not base.authors and other.authors:
        base.authors = other.authors
    if base.book_id is None and other.book_id is not None:
        base.book_id = other.book_id
    return base


def prefer_language(candidates: list[BookCandidate], language: str) -> list[BookCandidate]:
    """Поднимает книги на языке клуба наверх, ничего не выбрасывая.

    Жёстко ограничивать выдачу языком нельзя: клуб читает и в оригинале, и
    англоязычное издание для «круглого стола» — нормальный выбор. Но человек,
    ищущий «Солярис», ждёт русское издание первым, а не польское.
    """
    if not language:
        return candidates
    return sorted(candidates, key=lambda c: c.language != language)


def dedupe(groups: list[list[BookCandidate]]) -> list[BookCandidate]:
    """Склеивает списки кандидатов по ISBN-13, а при его отсутствии — по ключу
    «название|автор». Порядок первого списка сохраняется: он же и приоритетный."""
    merged: list[BookCandidate] = []
    by_isbn: dict[str, BookCandidate] = {}
    by_key: dict[str, BookCandidate] = {}

    for group in groups:
        for candidate in group:
            existing = None
            if candidate.isbn13 and candidate.isbn13 in by_isbn:
                existing = by_isbn[candidate.isbn13]
            elif candidate.key in by_key:
                existing = by_key[candidate.key]

            if existing is not None:
                combine(existing, candidate)
                # ISBN мог приехать только со вторым источником — тогда книга
                # становится findable по нему для следующих кандидатов.
                if existing.isbn13:
                    by_isbn.setdefault(existing.isbn13, existing)
                continue

            merged.append(candidate)
            by_key[candidate.key] = candidate
            if candidate.isbn13:
                by_isbn[candidate.isbn13] = candidate
    return merged


async def search_local(session: AsyncSession, query: str, limit: int = 20) -> list[Book]:
    pattern = f"%{query.strip()}%"
    stmt = (
        sa.select(Book)
        .where(
            Book.status == BookStatus.ACTIVE,
            sa.or_(
                Book.title.ilike(pattern),
                sa.func.array_to_string(Book.authors, " ").ilike(pattern),
            ),
        )
        .order_by(Book.title)
        .limit(limit)
    )
    return list((await session.execute(stmt)).scalars().all())


async def search(
    session: AsyncSession, query: str, *, limit: int = 20, external: bool = True
) -> tuple[list[BookCandidate], bool]:
    """Возвращает склеенную выдачу и признак «один из источников молчал».

    Внешние источники опрашиваются параллельно и независимо: недоступность
    одного не должна ронять поиск — иначе клуб остаётся без каталога из-за
    чужого сбоя.
    """
    local = [book_to_candidate(book) for book in await search_local(session, query, limit)]
    if not external or not query.strip():
        return local, False

    client = get_client()
    results = await asyncio.gather(
        google_books.search(client, query, limit),
        open_library.search(client, query, limit),
        return_exceptions=True,
    )

    groups: list[list[BookCandidate]] = [local]
    degraded = False
    for name, result in zip(("google_books", "open_library"), results, strict=True):
        if isinstance(result, BaseException):
            # У таймаутов httpx текст пустой — без имени класса в логе
            # осталась бы строка «не ответил: » без причины.
            logger.warning(
                "Источник %s не ответил: %s %s", name, type(result).__name__, result
            )
            degraded = True
            continue
        groups.append(result)

    return prefer_language(dedupe(groups), get_config().books_language), degraded


async def find_existing(
    session: AsyncSession, candidate: BookCandidate
) -> Book | None:
    """Ищет книгу в каталоге тремя способами: по внешнему id, по ISBN и по ключу.

    Порядок важен: внешний id — самый надёжный, он не зависит ни от написания
    названия, ни от того, как источник записал автора.
    """
    if candidate.book_id is not None:
        return await session.get(Book, candidate.book_id)

    source_row = (
        await session.execute(
            sa.select(BookSource).where(
                BookSource.source == candidate.source,
                BookSource.external_id == candidate.external_id,
            )
        )
    ).scalar_one_or_none()
    if source_row is not None:
        return await session.get(Book, source_row.book_id)

    if candidate.isbn13:
        book = (
            await session.execute(sa.select(Book).where(Book.isbn13 == candidate.isbn13))
        ).scalar_one_or_none()
        if book is not None:
            return book

    return (
        await session.execute(sa.select(Book).where(Book.dedup_key == candidate.key))
    ).scalar_one_or_none()


async def ensure_book(
    session: AsyncSession, candidate: BookCandidate, *, added_by: int | None = None
) -> Book:
    """Возвращает книгу из каталога, заводя её при первом обращении.

    Идемпотентна: повторный вызов с тем же кандидатом не создаёт второй записи,
    а лишь дописывает недостающую привязку к источнику.
    """
    book = await find_existing(session, candidate)
    if book is None:
        book = Book(
            title=candidate.title[:512],
            authors=candidate.authors,
            year=candidate.year,
            cover_url=candidate.cover_url,
            description=candidate.description,
            page_count=candidate.page_count,
            isbn13=candidate.isbn13,
            language=candidate.language,
            genres=candidate.genres,
            world_rating=candidate.world_rating,
            world_ratings_count=candidate.world_ratings_count,
            dedup_key=dedup_key(candidate.title, candidate.authors),
            added_by_user_id=added_by,
        )
        session.add(book)
        await session.flush()
    else:
        # Книга уже есть, но могла приехать без обложки или без ISBN.
        book.cover_url = book.cover_url or candidate.cover_url
        book.description = book.description or candidate.description
        book.isbn13 = book.isbn13 or candidate.isbn13
        book.page_count = book.page_count or candidate.page_count
        book.year = book.year or candidate.year
        # Известность обновляем, когда источник знает больше, чем мы записали.
        if (candidate.world_ratings_count or 0) > (book.world_ratings_count or 0):
            book.world_rating = candidate.world_rating
            book.world_ratings_count = candidate.world_ratings_count

    if candidate.source is not BookSourceKind.MANUAL:
        await session.execute(
            sa.dialects.postgresql.insert(BookSource)
            .values(
                book_id=book.id,
                source=candidate.source,
                external_id=candidate.external_id,
                payload=candidate.payload,
            )
            .on_conflict_do_nothing(index_elements=["source", "external_id"])
        )
    await session.flush()
    return book


async def fetch_external(source: str, external_id: str) -> BookCandidate | None:
    """Догружает карточку из источника — когда клиент просит завести книгу,
    которую видел в выдаче, а выдача уже неактуальна."""
    client = get_client()
    kind = BookSourceKind(source)
    if kind is BookSourceKind.GOOGLE_BOOKS:
        return await google_books.fetch(client, external_id)
    if kind is BookSourceKind.OPEN_LIBRARY:
        return await open_library.fetch(client, external_id)
    return None
