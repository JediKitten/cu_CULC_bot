from datetime import date, datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin
from app.models.enums import ReadingStatus, enum_col


class ReadingEntry(Base, CreatedAtMixin):
    """Строка читательского дневника: одна на пару «человек — книга».

    Оценка живёт здесь же, а не в отдельной таблице рейтингов: оценить книгу,
    не отметив её прочитанной, смысла не имеет, а одна строка на пару избавляет
    от вечного вопроса, где искать состояние.

    Оценка хранится в полубаллах 1..10 — на экране это пять звёзд с половинками.
    Дробей в базе нет, поэтому среднее считается точно.
    """

    __tablename__ = "reading_entries"
    __table_args__ = (
        sa.UniqueConstraint("user_id", "book_id", name="uq_reading_entry"),
        sa.CheckConstraint("score IS NULL OR score BETWEEN 1 AND 10", name="score_range"),
        sa.CheckConstraint(
            "favourite_position IS NULL OR favourite_position BETWEEN 1 AND 4",
            name="favourite_position_range",
        ),
        # Одно место в витрине занимает ровно одна книга.
        sa.Index(
            "uq_favourite_slot",
            "user_id",
            "favourite_position",
            unique=True,
            postgresql_where=sa.text("favourite_position IS NOT NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(sa.ForeignKey("users.id"), index=True)
    book_id: Mapped[int] = mapped_column(sa.ForeignKey("books.id"), index=True)
    status: Mapped[ReadingStatus] = mapped_column(enum_col(ReadingStatus, "reading_status"))
    started_on: Mapped[date | None] = mapped_column(sa.Date)
    finished_on: Mapped[date | None] = mapped_column(sa.Date)
    score: Mapped[int | None]
    review: Mapped[str | None] = mapped_column(sa.Text)
    # Отзыв виден другим участникам; закрытый остаётся личной заметкой.
    is_private: Mapped[bool] = mapped_column(default=False, server_default=sa.false())
    # Лайк — отдельная от оценки вещь: оценка говорит «насколько хорошо», лайк —
    # «моё». Книгу можно любить, не считая её лучшей, и наоборот.
    liked: Mapped[bool] = mapped_column(default=False, server_default=sa.false())
    # Место в четвёрке любимых на витрине профиля: 1..4 или пусто.
    favourite_position: Mapped[int | None]
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now()
    )
