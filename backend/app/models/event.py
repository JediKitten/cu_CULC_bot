from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin
from app.models.enums import (
    AttendanceMethod,
    DecidedBy,
    EventStatus,
    MemberKind,
    ParticipationState,
    enum_col,
)


class Event(Base, CreatedAtMixin):
    """Встреча по книге.

    Живёт от одобрения заявки до отзывов: организатор расставляет окна
    (slot_selection), участники выбирают удобные (voting), время закрепляется
    автоматом по дедлайну или организатором раньше (scheduled).
    """

    __tablename__ = "events"

    id: Mapped[int] = mapped_column(primary_key=True)
    book_id: Mapped[int] = mapped_column(sa.ForeignKey("books.id"), index=True)
    event_type_id: Mapped[int] = mapped_column(sa.ForeignKey("event_types.id"))
    organizer_user_id: Mapped[int] = mapped_column(sa.ForeignKey("users.id"), index=True)
    application_id: Mapped[int | None] = mapped_column(sa.ForeignKey("organizer_applications.id"))
    title: Mapped[str | None] = mapped_column(sa.String(256))
    description: Mapped[str | None] = mapped_column(sa.Text)
    place: Mapped[str | None] = mapped_column(sa.String(256))
    capacity: Mapped[int | None]
    min_attendance: Mapped[int | None]
    # Кому встреча доступна: пустой массив — всем. Значения — MemberKind.
    audience: Mapped[list[str]] = mapped_column(ARRAY(sa.String(16)), server_default="{}")
    status: Mapped[EventStatus] = mapped_column(
        enum_col(EventStatus, "event_status"),
        default=EventStatus.SLOT_SELECTION,
        server_default="slot_selection",
    )
    vote_deadline: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    slot_id: Mapped[int | None] = mapped_column(
        sa.ForeignKey("event_slots.id", use_alter=True, name="fk_events_slot_id_event_slots")
    )
    decided_by: Mapped[DecidedBy | None] = mapped_column(enum_col(DecidedBy, "decided_by"))
    decided_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    decision_note: Mapped[str | None] = mapped_column(sa.Text)
    # Код присутствия называют вслух на встрече. Ротируется, чтобы его нельзя
    # было переслать тому, кто не пришёл.
    attendance_code: Mapped[str | None] = mapped_column(sa.String(8))
    code_rotated_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    cancel_reason: Mapped[str | None] = mapped_column(sa.Text)
    published_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))

    @property
    def audience_kinds(self) -> set[MemberKind]:
        return {MemberKind(value) for value in self.audience}


class EventSlot(Base, CreatedAtMixin):
    """Окно, предложенное организатором."""

    __tablename__ = "event_slots"

    id: Mapped[int] = mapped_column(primary_key=True)
    event_id: Mapped[int] = mapped_column(
        sa.ForeignKey("events.id", ondelete="CASCADE"), index=True
    )
    starts_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True))
    duration_minutes: Mapped[int] = mapped_column(default=120, server_default="120")
    place: Mapped[str | None] = mapped_column(sa.String(256))
    note: Mapped[str | None] = mapped_column(sa.Text)


class SlotVote(Base, CreatedAtMixin):
    """Голос за окно. Голосов у человека столько, сколько окон ему подходит."""

    __tablename__ = "slot_votes"
    __table_args__ = (sa.UniqueConstraint("slot_id", "user_id", name="uq_slot_vote"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    event_id: Mapped[int] = mapped_column(
        sa.ForeignKey("events.id", ondelete="CASCADE"), index=True
    )
    slot_id: Mapped[int] = mapped_column(
        sa.ForeignKey("event_slots.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[int] = mapped_column(sa.ForeignKey("users.id"), index=True)


class Participation(Base, CreatedAtMixin):
    """Придёт ли человек на назначенную встречу."""

    __tablename__ = "participations"
    __table_args__ = (sa.UniqueConstraint("event_id", "user_id", name="uq_participation"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    event_id: Mapped[int] = mapped_column(
        sa.ForeignKey("events.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[int] = mapped_column(sa.ForeignKey("users.id"), index=True)
    state: Mapped[ParticipationState] = mapped_column(
        enum_col(ParticipationState, "participation_state")
    )
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now()
    )


class Attendance(Base, CreatedAtMixin):
    """Факт присутствия."""

    __tablename__ = "attendance"
    __table_args__ = (sa.UniqueConstraint("event_id", "user_id", name="uq_attendance"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    event_id: Mapped[int] = mapped_column(
        sa.ForeignKey("events.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[int] = mapped_column(sa.ForeignKey("users.id"), index=True)
    method: Mapped[AttendanceMethod] = mapped_column(
        enum_col(AttendanceMethod, "attendance_method")
    )
    marked_by: Mapped[int | None] = mapped_column(sa.ForeignKey("users.id"))


class EventFeedback(Base, CreatedAtMixin):
    """Отзыв о встрече. Оценка книги остаётся в дневнике — это разные вещи:
    встреча может быть отличной по скучной книге и наоборот."""

    __tablename__ = "event_feedback"
    __table_args__ = (
        sa.UniqueConstraint("event_id", "user_id", name="uq_event_feedback"),
        sa.CheckConstraint("score IS NULL OR score BETWEEN 1 AND 10", name="feedback_score_range"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    event_id: Mapped[int] = mapped_column(
        sa.ForeignKey("events.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[int] = mapped_column(sa.ForeignKey("users.id"), index=True)
    score: Mapped[int | None]
    text: Mapped[str | None] = mapped_column(sa.Text)
