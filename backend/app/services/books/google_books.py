"""Клиент Google Books.

Ключ не обязателен: без него работает тот же поиск, только с более жёсткими
лимитами. Базовый адрес берётся из конфига — на машине, где это писалось,
провайдер подменяет DNS части внешних API, и путь к зеркалу нужен без правки кода.
"""

import logging

import httpx

from app.config import get_config
from app.models.enums import BookSourceKind
from app.services.books.normalize import BookCandidate, clean_isbn13, year_of

logger = logging.getLogger(__name__)

SOURCE = BookSourceKind.GOOGLE_BOOKS


def _isbn13(identifiers: list[dict]) -> str | None:
    for item in identifiers or []:
        if item.get("type") == "ISBN_13":
            return clean_isbn13(item.get("identifier"))
    return None


def _cover(links: dict) -> str | None:
    url = links.get("thumbnail") or links.get("smallThumbnail")
    # Google отдаёт http и «загнутый уголок» картинки. Первое Telegram не
    # покажет вовсе, второе — просто некрасиво.
    return url.replace("http://", "https://").replace("&edge=curl", "") if url else None


def to_candidate(item: dict) -> BookCandidate | None:
    info = item.get("volumeInfo") or {}
    title = (info.get("title") or "").strip()
    if not title or not item.get("id"):
        return None
    subtitle = (info.get("subtitle") or "").strip()
    return BookCandidate(
        source=SOURCE,
        external_id=str(item["id"]),
        title=f"{title}. {subtitle}" if subtitle else title,
        authors=[a for a in (info.get("authors") or []) if a],
        year=year_of(info.get("publishedDate")),
        cover_url=_cover(info.get("imageLinks") or {}),
        description=info.get("description"),
        page_count=info.get("pageCount"),
        isbn13=_isbn13(info.get("industryIdentifiers") or []),
        language=info.get("language"),
        genres=list(info.get("categories") or []),
        payload=item,
    )


async def search(client: httpx.AsyncClient, query: str, limit: int = 20) -> list[BookCandidate]:
    config = get_config()
    params: dict[str, str | int] = {
        "q": query,
        "maxResults": min(limit, 40),
        "printType": "books",
        "orderBy": "relevance",
    }
    if config.google_books_api_key:
        params["key"] = config.google_books_api_key

    response = await client.get(f"{config.google_books_base_url}/volumes", params=params)
    response.raise_for_status()
    items = response.json().get("items") or []
    return [c for c in (to_candidate(item) for item in items) if c is not None]


async def fetch(client: httpx.AsyncClient, external_id: str) -> BookCandidate | None:
    config = get_config()
    params = {"key": config.google_books_api_key} if config.google_books_api_key else {}
    response = await client.get(
        f"{config.google_books_base_url}/volumes/{external_id}", params=params
    )
    if response.status_code == httpx.codes.NOT_FOUND:
        return None
    response.raise_for_status()
    return to_candidate(response.json())
