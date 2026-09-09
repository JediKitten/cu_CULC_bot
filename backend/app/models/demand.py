from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, CreatedAtMixin
from app.models.enums import EventTypeStatus, RevokeReason, enum_col


class EventType(Base, CreatedAtMixin):
    """Формат встречи. Семь встроенных засевает миграция, свой вариант может
    предложить организатор в заявке — он создаётся со status=pending и виден
    только в этой заявке, пока администратор не переведёт его в active."""

    __tablename__ = "event_types"

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(sa.String(64), unique=True)
    title: Mapped[str] = mapped_column(sa.String(128))
    description: Mapped[str | None] = mapped_column(sa.Text)
    # Нужно ли гостю читать книгу заранее. У круглого стола и мастер-класса —
    # нет, и это меняет и текст приглашения, и то, кого зовём.
    requires_reading: Mapped[bool] = mapped_column(default=True, server_default=sa.true())
    is_builtin: Mapped[bool] = mapped_column(default=False, server_default=sa.false())
    status: Mapped[EventTypeStatus] = mapped_column(
        enum_col(EventTypeStatus, "event_type_status"),
        default=EventTypeStatus.ACTIVE,
        server_default="active",
    )
    created_by_user_id: Mapped[int | None] = mapped_column(sa.ForeignKey("users.id"))
    sort_order: Mapped[int] = mapped_column(default=100, server_default="100")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<EventType {self.slug}>"


class Demand(Base, CreatedAtMixin):
    """«Хочу встречу по этой книге».

    Активная отметка одна на пару «человек — книга» — это обеспечивает
    частичный уникальный индекс. Снятая отметка не удаляется: по ней считается
    аналитика спроса, который так и не дошёл до встречи.
    """

    __tablename__ = "demands"
    __table_args__ = (
        sa.Index(
            "uq_demand_active",
            "user_id",
            "book_id",
            unique=True,
            postgresql_where=sa.text("revoked_at IS NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(sa.ForeignKey("users.id"), index=True)
    book_id: Mapped[int] = mapped_column(sa.ForeignKey("books.id"), index=True)
    # Снимок на момент отметки: читал ли человек книгу. Присоединиться к
    # ожидающим можно и не читая — для круглого стола это норма, — но
    # оргкомитету важно видеть, сколько из ожидающих книгу действительно знают.
    has_read: Mapped[bool] = mapped_column(default=False, server_default=sa.false())
    comment: Mapped[str | None] = mapped_column(sa.Text)
    revoked_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    revoke_reason: Mapped[RevokeReason | None] = mapped_column(
        enum_col(RevokeReason, "demand_revoke_reason")
    )

    types: Mapped[list["DemandType"]] = relationship(
        cascade="all, delete-orphan", lazy="selectin"
    )


class DemandType(Base):
    """Какие форматы встречи по этой книге человеку интересны. Множественный
    выбор — отсюда отдельная таблица, а не колонка."""

    __tablename__ = "demand_types"

    demand_id: Mapped[int] = mapped_column(
        sa.ForeignKey("demands.id", ondelete="CASCADE"), primary_key=True
    )
    event_type_id: Mapped[int] = mapped_column(sa.ForeignKey("event_types.id"), primary_key=True)
