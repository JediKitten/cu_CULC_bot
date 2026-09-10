"""Анкета и профиль.

Анкета делится надвое. Обязательную часть — имя, роль, почта — человек
проходит в боте: без неё в клубе делать нечего, и спрашивать её в Mini App
значило бы пускать внутрь того, о ком ничего не известно. Необязательную —
вкусы и предпочтения — предлагают уже в приложении, и любой вопрос можно
пропустить: неотвеченный вопрос честнее выдуманного ответа.
"""

import re
from datetime import UTC, datetime

import sqlalchemy as sa
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Profile, ProfileEventType
from app.models.demand import EventType
from app.models.enums import EMAIL_REQUIRED_KINDS, EventTypeStatus, MemberKind
from app.services.reference import clean_genres

# Домен студенческой почты ЦУ. Вынесен в константу: если появится второй
# домен, править нужно будет ровно здесь.
CU_EMAIL_DOMAINS = ("edu.centraluniversity.ru",)

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

DOMAINS_HUMAN = " или ".join(f"@{domain}" for domain in CU_EMAIL_DOMAINS)
NEED_EMAIL = f"Нужна студенческая почта в домене {DOMAINS_HUMAN}"
BAD_EMAIL = "Похоже, это не адрес почты"
WRONG_DOMAIN = f"Принимается только студенческая почта ЦУ: {DOMAINS_HUMAN}"
NEED_NAME = "Напишите фамилию и имя"

# Подписи ролей. Здесь же, а не в интерфейсе: их показывает и бот, и Mini App,
# и оргкомитет читает те же слова в аналитике.
KIND_TITLES: dict[MemberKind, str] = {
    MemberKind.APPLICANT: "Абитуриент",
    MemberKind.BACHELOR: "Бакалавр",
    MemberKind.MASTER: "Магистрант",
    MemberKind.STAFF: "Сотрудник",
    MemberKind.GUEST: "Внешний гость",
}


def email_required(kind: MemberKind) -> bool:
    return kind in EMAIL_REQUIRED_KINDS


class ProfileError(ValueError):
    """Ответ не подошёл. Текст показываем человеку как есть — и в боте, и в API."""


def clean_name(full_name: str | None) -> str:
    name = " ".join((full_name or "").split())
    if len(name) < 2:
        raise ProfileError(NEED_NAME)
    return name[:128]


def clean_email(kind: MemberKind, email: str | None) -> str | None:
    email = (email or "").strip().lower() or None

    if email is None:
        if email_required(kind):
            raise ProfileError(NEED_EMAIL)
        return None

    if not EMAIL_RE.match(email):
        raise ProfileError(BAD_EMAIL)
    if email.rsplit("@", 1)[1] not in CU_EMAIL_DOMAINS:
        raise ProfileError(WRONG_DOMAIN)
    return email


async def register(
    session: AsyncSession,
    user_id: int,
    *,
    full_name: str,
    member_kind: MemberKind,
    university_email: str | None,
) -> Profile:
    """Обязательная часть анкеты. Её принимает бот.

    Повторный проход не сбрасывает предпочтения: человек может вернуться и
    поправить роль или фамилию, не теряя всего остального.
    """
    name = clean_name(full_name)
    email = clean_email(member_kind, university_email)

    profile = await session.get(Profile, user_id)
    if profile is None:
        profile = Profile(user_id=user_id)
        session.add(profile)

    profile.full_name = name
    profile.member_kind = member_kind
    profile.university_email = email
    profile.updated_at = datetime.now(UTC)
    if profile.completed_at is None:
        profile.completed_at = datetime.now(UTC)

    await session.commit()
    await session.refresh(profile)
    return profile


async def save_preferences(
    session: AsyncSession,
    user_id: int,
    *,
    reading_pace=None,
    club_experience=None,
    genres: list[str] | None = None,
    event_type_ids: list[int] | None = None,
    about: str | None = None,
) -> Profile:
    """Необязательная часть. Любой вопрос можно пропустить — тогда поле
    остаётся пустым, и это нормальный ответ, а не ошибка.

    preferences_at проставляется в любом случае: важен факт, что человека
    спросили и он ответил, — иначе напоминание нечем унять.
    """
    profile = await session.get(Profile, user_id)
    if profile is None or profile.completed_at is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Сначала пройдите регистрацию в боте")

    profile.reading_pace = reading_pace
    profile.club_experience = club_experience
    profile.genres = clean_genres(genres)
    profile.about = (about or "").strip() or None
    profile.preferences_at = datetime.now(UTC)
    profile.updated_at = datetime.now(UTC)

    await session.flush()
    await set_event_types(session, user_id, event_type_ids or [])
    await session.commit()
    await session.refresh(profile)
    return profile


async def update_identity(
    session: AsyncSession,
    user_id: int,
    *,
    full_name: str,
    member_kind: MemberKind,
    university_email: str | None,
) -> Profile:
    """Правка обязательной части из приложения. Правила те же, что в боте:
    сменил роль на студенческую без почты — сохранение не проходит."""
    try:
        return await register(
            session,
            user_id,
            full_name=full_name,
            member_kind=member_kind,
            university_email=university_email,
        )
    except ProfileError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc


async def dismiss_reminder(session: AsyncSession, user_id: int, *, forever: bool) -> None:
    """Плашка «допройти анкету»: спрятать до следующего запуска бота или
    насовсем. Временное скрытие снимает /start — так человек, который просто
    отмахнулся, увидит напоминание ещё раз, а тот, кто отказался, не увидит."""
    profile = await session.get(Profile, user_id)
    if profile is None:
        return
    if forever:
        profile.reminder_dismissed = True
    else:
        profile.reminder_hidden_at = datetime.now(UTC)
    await session.commit()


async def unhide_reminder(session: AsyncSession, user_id: int) -> None:
    """Снимает временное скрытие. Зовётся из /start."""
    await session.execute(
        sa.update(Profile)
        .where(Profile.user_id == user_id, Profile.reminder_dismissed.is_(False))
        .values(reminder_hidden_at=None)
    )
    await session.commit()


def needs_preferences(profile: Profile | None) -> bool:
    """Показывать ли плашку «допройти анкету»."""
    if profile is None or profile.completed_at is None:
        return False
    return (
        profile.preferences_at is None
        and not profile.reminder_dismissed
        and profile.reminder_hidden_at is None
    )


async def set_event_types(session: AsyncSession, user_id: int, ids: list[int]) -> None:
    """Интересные форматы. Скрытые и ещё не одобренные не принимаем: иначе
    в анкете осел бы формат, который оргкомитет отверг."""
    allowed: set[int] = set()
    if ids:
        allowed = set(
            (
                await session.execute(
                    sa.select(EventType.id).where(
                        EventType.id.in_(ids), EventType.status == EventTypeStatus.ACTIVE
                    )
                )
            )
            .scalars()
            .all()
        )
    await session.execute(
        sa.delete(ProfileEventType).where(ProfileEventType.profile_id == user_id)
    )
    for event_type_id in allowed:
        session.add(ProfileEventType(profile_id=user_id, event_type_id=event_type_id))
    await session.flush()
