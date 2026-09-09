"""Приведение книжных данных к одному виду.

Одна и та же книга приходит из двух источников по-разному: «Лев Николаевич
Толстой» против «Leo Tolstoy», «Война и мир» против «Война и мир. Том 1».
Здесь всё, что превращает такие строки в сопоставимые ключи.
"""

import re
import unicodedata
from dataclasses import dataclass, field

from app.models.enums import BookSourceKind

_PUNCT = re.compile(r"[^\w\s]", re.UNICODE)
_SPACES = re.compile(r"\s+")
# Хвосты вида «(мягкая обложка)», «: роман», «. Том 1» отбрасывать не пытаемся:
# «Том 1» и «Том 2» — разные книги, и склеить их было бы хуже, чем показать
# рядом две похожие строки.


def norm(value: str | None) -> str:
    """Строка без регистра, пунктуации, ё и лишних пробелов."""
    if not value:
        return ""
    text = unicodedata.normalize("NFKC", value).casefold().replace("ё", "е")
    text = _PUNCT.sub(" ", text)
    return _SPACES.sub(" ", text).strip()


def dedup_key(title: str, authors: list[str] | None) -> str:
    """Ключ уникальности книги в каталоге: «название|первый автор».

    Автор входит в ключ намеренно. Без него две разные книги с одинаковым
    названием — а таких много — просто нельзя было бы завести: вторую отбил бы
    уникальный индекс. С автором худший исход мягче: изредка появится дубль
    одной книги, записанной в источниках разными именами автора, и его
    администратор скроет руками. Основную склейку всё равно делает ISBN.
    """
    first_author = (authors or [""])[0]
    return f"{norm(title)}|{norm(first_author)}"


def clean_isbn13(value: str | None) -> str | None:
    if not value:
        return None
    digits = re.sub(r"[^0-9Xx]", "", value)
    return digits if len(digits) == 13 and digits.isdigit() else None


def year_of(value: str | int | None) -> int | None:
    """Год из «1869», «1869-01-01», 1869 и прочего мусора."""
    if value is None:
        return None
    match = re.search(r"\d{4}", str(value))
    if not match:
        return None
    year = int(match.group())
    return year if 1 <= year <= 2100 else None


@dataclass(slots=True)
class BookCandidate:
    """Книга в общем виде — из источника или уже из каталога."""

    source: BookSourceKind
    external_id: str
    title: str
    authors: list[str] = field(default_factory=list)
    year: int | None = None
    cover_url: str | None = None
    description: str | None = None
    page_count: int | None = None
    isbn13: str | None = None
    language: str | None = None
    genres: list[str] = field(default_factory=list)
    payload: dict = field(default_factory=dict)
    # Заполнено, если книга уже заведена в каталоге.
    book_id: int | None = None

    @property
    def key(self) -> str:
        return dedup_key(self.title, self.authors)
