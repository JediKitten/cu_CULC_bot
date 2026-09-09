"""Анкета и профиль.

Здесь же живёт правило вузовской почты: у студента и сотрудника она
обязательна, у абитуриента и внешнего гостя её может не быть вовсе. Правило
одно и то же и при первом заполнении, и при правке профиля — сменил «гостя»
на «студента», не вписав почту, сохранение не проходит.
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

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

NEED_EMAIL = "Для студентов и сотрудников вузовская почта обязательна"
BAD_EMAIL = "Похоже, это не адрес почты"
NEED_NAME = "Как вас зовут?"


def email_required(kind: MemberKind) -> bool:
    return kind in EMAIL_REQUIRED_KINDS


def validate(kind: MemberKind, full_name: str | None, email: str | None) -> str | None:
    """Возвращает нормализованную почту либо поднимает 400 с человеческим текстом."""
    if not (full_name or "").strip():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, NEED_NAME)

    email = (email or "").strip().lower() or None
    if email_required(kind):
        if email is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, NEED_EMAIL)
        if not EMAIL_RE.match(email):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, BAD_EMAIL)
    elif email is not None and not EMAIL_RE.match(email):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, BAD_EMAIL)
    return email


async def save(
    session: AsyncSession,
    user_id: int,
    *,
    member_kind: MemberKind,
    full_name: str,
    faculty: str | None,
    year: int | None,
    university_email: str | None,
    reading_pace,
    club_experience,
    genres: list[str] | None,
    event_type_ids: list[int] | None,
    about: str | None,
) -> Profile:
    """Создаёт или обновляет анкету. Первое успешное сохранение проставляет
    completed_at — именно оно открывает человеку остальное приложение."""
    email = validate(member_kind, full_name, university_email)
    # Факультет и курс осмысленны только у своих: гость с «курсом» — мусор,
    # который потом всплывёт в аналитике по факультетам.
    if member_kind not in (MemberKind.STUDENT, MemberKind.STAFF, MemberKind.APPLICANT):
        faculty, year = None, None
    if member_kind != MemberKind.STUDENT:
        year = None

    profile = await session.get(Profile, user_id)
    if profile is None:
        profile = Profile(user_id=user_id)
        session.add(profile)

    profile.member_kind = member_kind
    profile.full_name = full_name.strip()
    profile.faculty = (faculty or "").strip() or None
    profile.year = year
    profile.university_email = email
    profile.reading_pace = reading_pace
    profile.club_experience = club_experience
    profile.genres = clean_genres(genres)
    profile.about = (about or "").strip() or None
    profile.updated_at = datetime.now(UTC)
    if profile.completed_at is None:
        profile.completed_at = datetime.now(UTC)

    await session.flush()
    await set_event_types(session, user_id, event_type_ids or [])
    await session.commit()
    await session.refresh(profile)
    return profile


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
