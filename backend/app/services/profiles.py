"""Анкета и профиль.

Здесь же живут все правила, которые нельзя выразить схемой:

* почта ЦУ обязательна студентам и сотрудникам и проверяется по домену;
* ступень обучения спрашивают только у студентов;
* направление — только у бакалавров, магистрантам его не задают вовсе;
* «ещё не определился» доступно только первокурсникам.

Правила одни и те же при первом заполнении и при правке профиля: сменил
«гостя» на «студента», не вписав почту, — сохранение не проходит.
"""

import re
from datetime import UTC, datetime

import sqlalchemy as sa
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Profile, ProfileEventType
from app.models.demand import EventType
from app.models.enums import (
    EMAIL_REQUIRED_KINDS,
    UNDECIDED_MAX_YEAR,
    EventTypeStatus,
    MemberKind,
    Program,
    StudyLevel,
)
from app.services.reference import clean_genres

# Домен почты ЦУ. Вынесен в константу: если у сотрудников адреса окажутся
# в другом домене, править нужно будет ровно здесь.
CU_EMAIL_DOMAINS = ("edu.centraluniversity.ru",)

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

DOMAINS_HUMAN = " или ".join(f"@{domain}" for domain in CU_EMAIL_DOMAINS)
NEED_EMAIL = f"Нужна почта ЦУ в домене {DOMAINS_HUMAN}"
BAD_EMAIL = "Похоже, это не адрес почты"
WRONG_DOMAIN = f"Принимается только почта ЦУ: {DOMAINS_HUMAN}"
NEED_NAME = "Как вас зовут?"
NEED_LEVEL = "Выберите ступень: бакалавриат или магистратура"
NEED_PROGRAM = "Выберите направление"
UNDECIDED_ONLY_FIRST_YEAR = (
    "«Ещё не определился» — только для первого курса. Со второго направление уже выбрано."
)


def email_required(kind: MemberKind) -> bool:
    return kind in EMAIL_REQUIRED_KINDS


def check_email(kind: MemberKind, email: str | None) -> str | None:
    """Возвращает нормализованную почту либо поднимает 400 с человеческим текстом."""
    email = (email or "").strip().lower() or None

    if email is None:
        if email_required(kind):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, NEED_EMAIL)
        return None

    if not EMAIL_RE.match(email):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, BAD_EMAIL)

    domain = email.rsplit("@", 1)[1]
    if domain not in CU_EMAIL_DOMAINS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, WRONG_DOMAIN)
    return email


def check_study(
    kind: MemberKind,
    study_level: StudyLevel | None,
    program: Program | None,
    year: int | None,
) -> tuple[StudyLevel | None, Program | None, int | None]:
    """Согласует ступень, направление и курс.

    Возвращает их приведёнными к тому виду, в котором они осмысленны: у всех,
    кроме студентов, ступени и направления нет, у магистрантов нет направления.
    Лишнее не отвергаем с ошибкой, а обнуляем — иначе клиент, приславший старое
    значение вместе с новой категорией, получал бы отказ там, где всё понятно.
    """
    if kind is not MemberKind.STUDENT:
        return None, None, None

    if study_level is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, NEED_LEVEL)

    if study_level is StudyLevel.MASTER:
        # Магистрантов о направлении не спрашиваем вовсе.
        return study_level, None, year

    if program is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, NEED_PROGRAM)
    if program is Program.UNDECIDED and (year or 0) > UNDECIDED_MAX_YEAR:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, UNDECIDED_ONLY_FIRST_YEAR)
    return study_level, program, year


def validate(kind: MemberKind, full_name: str | None, email: str | None) -> str | None:
    if not (full_name or "").strip():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, NEED_NAME)
    return check_email(kind, email)


async def save(
    session: AsyncSession,
    user_id: int,
    *,
    member_kind: MemberKind,
    full_name: str,
    study_level: StudyLevel | None,
    program: Program | None,
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
    study_level, program, year = check_study(member_kind, study_level, program, year)

    profile = await session.get(Profile, user_id)
    if profile is None:
        profile = Profile(user_id=user_id)
        session.add(profile)

    profile.member_kind = member_kind
    profile.full_name = full_name.strip()
    profile.study_level = study_level
    profile.program = program
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
