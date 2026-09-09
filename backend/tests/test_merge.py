"""Склейка книг из двух источников.

Это место, где проект живёт или не живёт: если каталог наполнится дублями,
спрос по книге размажется на две карточки и биржа перестанет работать.
"""

import httpx
import pytest

from app.models import Book, BookSource
from app.models.enums import BookSourceKind
from app.services.books import merge
from app.services.books.normalize import BookCandidate, dedup_key, norm


def candidate(source, external_id, title, authors, **kwargs) -> BookCandidate:
    return BookCandidate(
        source=source, external_id=external_id, title=title, authors=authors, **kwargs
    )


def test_norm_ignores_case_punctuation_and_yo():
    assert norm("Ёлки-палки, том 1!") == norm("елки палки том 1")


def test_dedup_key_keeps_author():
    """Две разные книги с одинаковым названием должны остаться разными:
    иначе вторую просто нельзя было бы завести."""
    assert dedup_key("Метро 2033", ["Дмитрий Глуховский"]) != dedup_key("Метро 2033", ["Иван Петров"])


def test_dedupe_merges_by_isbn():
    google = candidate(
        BookSourceKind.GOOGLE_BOOKS, "g1", "Война и мир", ["Лев Толстой"], isbn13="9781234567890"
    )
    # Название и автор записаны иначе, но ISBN тот же — это одна книга.
    openlib = candidate(
        BookSourceKind.OPEN_LIBRARY,
        "OL1W",
        "War and Peace",
        ["Leo Tolstoy"],
        isbn13="9781234567890",
        cover_url="https://covers/1.jpg",
        page_count=1300,
    )

    merged = merge.dedupe([[google], [openlib]])

    assert len(merged) == 1
    assert merged[0].source is BookSourceKind.GOOGLE_BOOKS
    # Приоритет Google Books: его название побеждает.
    assert merged[0].title == "Война и мир"
    # Пустые поля добираются у второго источника.
    assert merged[0].cover_url == "https://covers/1.jpg"
    assert merged[0].page_count == 1300


def test_dedupe_merges_by_title_and_author_without_isbn():
    google = candidate(BookSourceKind.GOOGLE_BOOKS, "g2", "Идиот", ["Фёдор Достоевский"])
    openlib = candidate(
        BookSourceKind.OPEN_LIBRARY,
        "OL2W",
        "Идиот!",
        ["Федор Достоевский"],
        cover_url="https://covers/2.jpg",
    )

    merged = merge.dedupe([[google], [openlib]])

    assert len(merged) == 1
    assert merged[0].cover_url == "https://covers/2.jpg"


def test_dedupe_keeps_different_books_apart():
    first = candidate(BookSourceKind.GOOGLE_BOOKS, "g3", "Метро 2033", ["Дмитрий Глуховский"])
    second = candidate(BookSourceKind.OPEN_LIBRARY, "OL3W", "Метро 2033", ["Иван Петров"])

    assert len(merge.dedupe([[first], [second]])) == 2


def test_local_book_wins_and_carries_id():
    local = candidate(
        BookSourceKind.MANUAL, "7", "Дюна", ["Фрэнк Герберт"], book_id=7
    )
    google = candidate(
        BookSourceKind.GOOGLE_BOOKS, "g4", "Дюна", ["Фрэнк Герберт"], cover_url="https://c/d.jpg"
    )

    merged = merge.dedupe([[local], [google]])

    assert len(merged) == 1
    assert merged[0].book_id == 7
    assert merged[0].cover_url == "https://c/d.jpg"


async def test_search_survives_dead_source(session, monkeypatch):
    """Падение одного источника не должно ронять поиск: клуб не может остаться
    без каталога из-за чужого сбоя."""

    async def boom(*args, **kwargs):
        raise httpx.ConnectError("DNS подменили")

    async def works(*args, **kwargs):
        return [candidate(BookSourceKind.OPEN_LIBRARY, "OL9W", "Обломов", ["Иван Гончаров"])]

    monkeypatch.setattr("app.services.books.google_books.search", boom)
    monkeypatch.setattr("app.services.books.open_library.search", works)

    found, degraded = await merge.search(session, "Обломов")

    assert degraded is True
    assert [c.title for c in found] == ["Обломов"]


async def test_ensure_book_is_idempotent(session):
    """Повторный вызов не плодит вторую книгу и дописывает вторую привязку."""
    google = candidate(
        BookSourceKind.GOOGLE_BOOKS, "g5", "Мастер и Маргарита", ["Михаил Булгаков"]
    )
    first = await merge.ensure_book(session, google)
    again = await merge.ensure_book(session, google)
    assert first.id == again.id

    openlib = candidate(
        BookSourceKind.OPEN_LIBRARY,
        "OL5W",
        "Мастер и Маргарита",
        ["Михаил Булгаков"],
        cover_url="https://covers/mm.jpg",
    )
    third = await merge.ensure_book(session, openlib)
    await session.commit()

    assert third.id == first.id
    # Обложка, которой не было, приехала со вторым источником.
    assert third.cover_url == "https://covers/mm.jpg"

    books = (await session.execute(__import__("sqlalchemy").select(Book))).scalars().all()
    sources = (await session.execute(__import__("sqlalchemy").select(BookSource))).scalars().all()
    assert len(books) == 1
    assert {s.source for s in sources} == {
        BookSourceKind.GOOGLE_BOOKS,
        BookSourceKind.OPEN_LIBRARY,
    }
