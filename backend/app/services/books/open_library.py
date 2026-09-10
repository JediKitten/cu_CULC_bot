"""Клиент Open Library. Ключа не требует вовсе.

Русскоязычный фонд у него слабее, чем у Google Books, поэтому он идёт вторым
источником: добирает то, чего первый не знает, и заполняет пустые поля.
"""

import logging

import httpx

from app.config import get_config
from app.models.enums import BookSourceKind
from app.services.books.normalize import BookCandidate, clean_isbn13, year_of

logger = logging.getLogger(__name__)

SOURCE = BookSourceKind.OPEN_LIBRARY

# Поля запрашиваем явно: ответ по умолчанию огромен, а нужно из него немногое.
FIELDS = ",".join(
    (
        "key",
        "title",
        "subtitle",
        "author_name",
        "first_publish_year",
        "cover_i",
        "isbn",
        "language",
        "subject",
        "number_of_pages_median",
        "ratings_average",
        "ratings_count",
        "readinglog_count",
    )
)


def _work_id(key: str | None) -> str | None:
    """«/works/OL12345W» → «OL12345W»."""
    return key.rsplit("/", 1)[-1] if key else None


def clean_title(title: str) -> str:
    """Убирает транслитерационный хвост.

    Open Library часто хранит название как «Война и мир / Voĭna i mir» —
    вторая половина здесь не подзаголовок, а та же строка латиницей.
    Отрезаем её, только когда первая часть кириллическая, а вторая нет:
    у настоящих двойных названий обе половины на одном языке.
    """
    if " / " not in title:
        return title
    left, right = title.split(" / ", 1)
    cyrillic = any("а" <= c.lower() <= "я" for c in left)
    latin_only = not any("а" <= c.lower() <= "я" for c in right)
    return left.strip() if cyrillic and latin_only else title


def to_candidate(doc: dict) -> BookCandidate | None:
    title = clean_title((doc.get("title") or "").strip())
    external_id = _work_id(doc.get("key"))
    if not title or not external_id:
        return None

    isbn13 = next(
        (cleaned for raw in (doc.get("isbn") or []) if (cleaned := clean_isbn13(raw))), None
    )
    cover = doc.get("cover_i")
    subtitle = (doc.get("subtitle") or "").strip()
    return BookCandidate(
        source=SOURCE,
        external_id=external_id,
        title=f"{title}. {subtitle}" if subtitle else title,
        authors=[a for a in (doc.get("author_name") or []) if a],
        year=year_of(doc.get("first_publish_year")),
        cover_url=f"https://covers.openlibrary.org/b/id/{cover}-L.jpg" if cover else None,
        description=None,  # в выдаче поиска его нет, за ним нужен отдельный запрос
        page_count=doc.get("number_of_pages_median"),
        isbn13=isbn13,
        language=(doc.get("language") or [None])[0],
        genres=list((doc.get("subject") or [])[:8]),
        world_rating=doc.get("ratings_average"),
        # Оценок в Open Library мало, а полок — много: если голосов нет,
        # известность лучше показывает число людей, добавивших книгу себе.
        world_ratings_count=doc.get("ratings_count") or doc.get("readinglog_count"),
        payload=doc,
    )


async def search(client: httpx.AsyncClient, query: str, limit: int = 20) -> list[BookCandidate]:
    config = get_config()
    response = await client.get(
        f"{config.open_library_base_url}/search.json",
        params={"q": query, "limit": limit, "fields": FIELDS},
    )
    response.raise_for_status()
    docs = response.json().get("docs") or []
    return [c for c in (to_candidate(doc) for doc in docs) if c is not None]


async def fetch(client: httpx.AsyncClient, external_id: str) -> BookCandidate | None:
    config = get_config()
    response = await client.get(
        f"{config.open_library_base_url}/search.json",
        params={"q": f"key:/works/{external_id}", "limit": 1, "fields": FIELDS},
    )
    response.raise_for_status()
    docs = response.json().get("docs") or []
    return to_candidate(docs[0]) if docs else None
