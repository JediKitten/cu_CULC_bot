from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin
from app.models.enums import BookSourceKind, BookStatus, RequestStatus, enum_col


class Book(Base, CreatedAtMixin):
    """Книга в каталоге клуба.

    Канонические поля собираются из Google Books и Open Library (при конфликте
    выигрывает первый) либо заводятся руками. Дублей быть не должно: одна и та
    же книга приходит из двух источников и в разных изданиях, поэтому ключей
    уникальности два — ISBN-13, если он есть, и нормализованное «автор|название».
    """

    __tablename__ = "books"
    __table_args__ = (
        sa.UniqueConstraint("dedup_key", name="uq_books_dedup_key"),
        sa.Index(
            "uq_books_isbn13",
            "isbn13",
            unique=True,
            postgresql_where=sa.text("isbn13 IS NOT NULL"),
        ),
        sa.Index(
            "ix_books_title_trgm",
            "title",
            postgresql_using="gin",
            postgresql_ops={"title": "gin_trgm_ops"},
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(sa.String(512))
    authors: Mapped[list[str]] = mapped_column(ARRAY(sa.String(256)), server_default="{}")
    year: Mapped[int | None]
    cover_url: Mapped[str | None] = mapped_column(sa.String(1024))
    description: Mapped[str | None] = mapped_column(sa.Text)
    page_count: Mapped[int | None]
    isbn13: Mapped[str | None] = mapped_column(sa.String(13))
    language: Mapped[str | None] = mapped_column(sa.String(8))
    genres: Mapped[list[str]] = mapped_column(ARRAY(sa.String(64)), server_default="{}")
    status: Mapped[BookStatus] = mapped_column(
        enum_col(BookStatus, "book_status"), default=BookStatus.ACTIVE, server_default="active"
    )
    # Нормализованное «первый автор|название»: нижний регистр, без пунктуации,
    # ё → е, схлопнутые пробелы. Строится в services/books/merge.py.
    dedup_key: Mapped[str] = mapped_column(sa.String(512))
    added_by_user_id: Mapped[int | None] = mapped_column(sa.ForeignKey("users.id"))

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Book {self.id} {self.title!r}>"


class BookSource(Base, CreatedAtMixin):
    """Привязка книги к записи во внешнем источнике.

    Строк может быть несколько на одну книгу — по одной на источник. Благодаря
    им повторный поиск узнаёт уже заведённую книгу по внешнему id, не полагаясь
    на нормализацию названия.
    """

    __tablename__ = "book_sources"
    __table_args__ = (
        sa.UniqueConstraint("source", "external_id", name="uq_book_source_external"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    book_id: Mapped[int] = mapped_column(sa.ForeignKey("books.id", ondelete="CASCADE"), index=True)
    source: Mapped[BookSourceKind] = mapped_column(enum_col(BookSourceKind, "book_source_kind"))
    external_id: Mapped[str] = mapped_column(sa.String(128))
    # Сырой ответ источника: пригодится, когда понадобится поле, о котором
    # сейчас не думали, — не идти же за ним в сеть заново.
    payload: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")


class BookRequest(Base, CreatedAtMixin):
    """Заявка завести книгу руками — когда источники её не знают или врут."""

    __tablename__ = "book_requests"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(sa.ForeignKey("users.id"), index=True)
    title: Mapped[str] = mapped_column(sa.String(512))
    authors: Mapped[list[str]] = mapped_column(ARRAY(sa.String(256)), server_default="{}")
    year: Mapped[int | None]
    isbn13: Mapped[str | None] = mapped_column(sa.String(13))
    cover_url: Mapped[str | None] = mapped_column(sa.String(1024))
    description: Mapped[str | None] = mapped_column(sa.Text)
    comment: Mapped[str | None] = mapped_column(sa.Text)
    status: Mapped[RequestStatus] = mapped_column(
        enum_col(RequestStatus, "book_request_status"),
        default=RequestStatus.PENDING,
        server_default="pending",
    )
    book_id: Mapped[int | None] = mapped_column(sa.ForeignKey("books.id"))
    reviewed_by: Mapped[int | None] = mapped_column(sa.ForeignKey("users.id"))
    reviewed_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    decision_comment: Mapped[str | None] = mapped_column(sa.Text)
