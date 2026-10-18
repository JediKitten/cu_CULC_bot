from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin
from app.models.enums import ApplicationStatus, MemberKind, RoomStatus, enum_col


class MeetingRoom(Base, CreatedAtMixin):
    """Форум оргкомитета — супергруппа с темами, где бот администратор.

    Бот не умеет создавать чаты, зато умеет заводить темы. Поэтому группу
    один раз создаёт человек, а бот под каждую заявку открывает в ней тему и
    удаляет её, когда встреча прошла или не состоялась. Подробности — в
    services/rooms.py. Таблица называется по-старому: раньше здесь был пул
    отдельных чатов-«переговорок».
    """

    __tablename__ = "meeting_rooms"

    id: Mapped[int] = mapped_column(primary_key=True)
    chat_id: Mapped[int] = mapped_column(sa.BigInteger, unique=True)
    title: Mapped[str] = mapped_column(sa.String(128))
    # free — рабочий, disabled — отключён. busy остался от пула чатов.
    status: Mapped[RoomStatus] = mapped_column(
        enum_col(RoomStatus, "room_status"), default=RoomStatus.FREE, server_default="free"
    )
    added_by: Mapped[int | None] = mapped_column(sa.ForeignKey("users.id"))
    # Когда бот последний раз убедился, что он здесь админ с нужными правами.
    checked_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    check_error: Mapped[str | None] = mapped_column(sa.Text)


class OrganizerApplication(Base, CreatedAtMixin):
    """Заявка «хотел бы организовать встречу по этой книге»."""

    __tablename__ = "organizer_applications"
    __table_args__ = (
        sa.Index(
            "uq_application_open",
            "user_id",
            "book_id",
            unique=True,
            postgresql_where=sa.text("status IN ('submitted', 'chat_open')"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(sa.ForeignKey("users.id"), index=True)
    book_id: Mapped[int] = mapped_column(sa.ForeignKey("books.id"), index=True)
    event_type_id: Mapped[int | None] = mapped_column(sa.ForeignKey("event_types.id"))
    # Свой формат, которого ещё нет в справочнике. Пока заявку не одобрили,
    # он живёт строкой; при одобрении администратор либо заводит новый
    # EventType, либо привязывает к существующему.
    proposed_type_title: Mapped[str | None] = mapped_column(sa.String(128))
    # Ответы опроса. Вопросы описаны в services/applications.py и будут
    # меняться — хранить их колонками значит мигрировать базу ради формулировки.
    answers: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    status: Mapped[ApplicationStatus] = mapped_column(
        enum_col(ApplicationStatus, "application_status"),
        default=ApplicationStatus.SUBMITTED,
        server_default="submitted",
    )
    room_id: Mapped[int | None] = mapped_column(sa.ForeignKey("meeting_rooms.id"))
    # Тема в форуме (message_thread_id). Пусто — темы нет или её уже удалили.
    topic_id: Mapped[int | None] = mapped_column(sa.Integer)
    invite_link: Mapped[str | None] = mapped_column(sa.String(512))
    chat_opened_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    # Кому встреча будет доступна. Заполняется администратором при одобрении;
    # пустой массив означает «всем».
    audience: Mapped[list[str]] = mapped_column(ARRAY(sa.String(16)), server_default="{}")
    reviewed_by: Mapped[int | None] = mapped_column(sa.ForeignKey("users.id"))
    reviewed_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    decision_comment: Mapped[str | None] = mapped_column(sa.Text)

    @property
    def audience_kinds(self) -> set[MemberKind]:
        return {MemberKind(value) for value in self.audience}
