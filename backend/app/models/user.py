from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, CreatedAtMixin
from app.models.enums import (
    ClubExperience,
    FriendshipStatus,
    MemberKind,
    ReadingPace,
    UserRole,
    enum_col,
)


class User(Base, CreatedAtMixin):
    """Аккаунт. Один Telegram = один участник: другого входа нет."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    tg_id: Mapped[int] = mapped_column(sa.BigInteger, unique=True)
    tg_username: Mapped[str | None] = mapped_column(sa.String(64))
    display_name: Mapped[str] = mapped_column(sa.String(128))
    photo_url: Mapped[str | None] = mapped_column(sa.String(512))
    role: Mapped[UserRole] = mapped_column(
        enum_col(UserRole, "user_role"), default=UserRole.USER, server_default="user"
    )
    tz: Mapped[str] = mapped_column(
        sa.String(64), default="Europe/Moscow", server_default="Europe/Moscow"
    )
    last_seen_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    # Показывали ли знакомство с ботом. Хранится отдельно от created_at: аккаунт
    # заводится первым запросом Mini App, а /start может случиться позже.
    onboarded_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    is_active: Mapped[bool] = mapped_column(default=True, server_default=sa.true())

    profile: Mapped["Profile | None"] = relationship(back_populates="user", lazy="selectin")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<User {self.id} {self.display_name!r} {self.role}>"


class Profile(Base):
    """Ответы анкеты. Отдельной таблицей: анкета будет расти и меняться,
    а users читает каждый запрос — таскать с собой факультет и жанры незачем.

    Обязательность вузовской почты для студентов и сотрудников проверяет
    services/profiles.py, а не CHECK: правило должно давать человеку внятное
    сообщение, а не ошибку драйвера, и работать одинаково при регистрации
    и при смене категории в профиле.
    """

    __tablename__ = "profiles"

    user_id: Mapped[int] = mapped_column(sa.ForeignKey("users.id"), primary_key=True)
    member_kind: Mapped[MemberKind] = mapped_column(enum_col(MemberKind, "member_kind"))
    full_name: Mapped[str] = mapped_column(sa.String(128))
    faculty: Mapped[str | None] = mapped_column(sa.String(128))
    year: Mapped[int | None]
    university_email: Mapped[str | None] = mapped_column(sa.String(255))
    reading_pace: Mapped[ReadingPace | None] = mapped_column(enum_col(ReadingPace, "reading_pace"))
    club_experience: Mapped[ClubExperience | None] = mapped_column(
        enum_col(ClubExperience, "club_experience")
    )
    # Жанры — свободный список строк из справочника services/reference.py.
    # Отдельной таблицы не заводим: это ответ анкеты, а не сущность со связями.
    genres: Mapped[list[str]] = mapped_column(ARRAY(sa.String(64)), server_default="{}")
    about: Mapped[str | None] = mapped_column(sa.Text)
    completed_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now()
    )

    user: Mapped[User] = relationship(back_populates="profile")
    event_types: Mapped[list["ProfileEventType"]] = relationship(
        cascade="all, delete-orphan", lazy="selectin"
    )


class ProfileEventType(Base):
    """Форматы встреч, которые человеку интересны. Здесь настоящая связь —
    форматы редактируются оргкомитетом и живут в своей таблице."""

    __tablename__ = "profile_event_types"

    profile_id: Mapped[int] = mapped_column(sa.ForeignKey("profiles.user_id"), primary_key=True)
    event_type_id: Mapped[int] = mapped_column(sa.ForeignKey("event_types.id"), primary_key=True)


class Friendship(Base, CreatedAtMixin):
    """Дружба как заявка: инициатор и адресат. Уникальность по паре, чтобы
    встречные заявки не плодили две строки — вторая просто принимает первую."""

    __tablename__ = "friendships"
    __table_args__ = (
        sa.UniqueConstraint("from_user_id", "to_user_id", name="uq_friendship_pair"),
        sa.CheckConstraint("from_user_id <> to_user_id", name="no_self_friendship"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    from_user_id: Mapped[int] = mapped_column(sa.ForeignKey("users.id"), index=True)
    to_user_id: Mapped[int] = mapped_column(sa.ForeignKey("users.id"), index=True)
    status: Mapped[FriendshipStatus] = mapped_column(
        enum_col(FriendshipStatus, "friendship_status"),
        default=FriendshipStatus.PENDING,
        server_default="pending",
    )
    decided_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
