"""Аналитика оргкомитета.

Вопрос, на который отвечает эта вкладка, один: где конвейер клуба буксует.
Поэтому в основе воронка «спрос → заявка → одобрение → встреча → явка», а
разрезы — по формату встречи и по факультету.
"""

from typing import Annotated

import sqlalchemy as sa
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import RequireAdmin
from app.db import get_session
from app.models import (
    Attendance,
    Book,
    Demand,
    Event,
    EventFeedback,
    EventType,
    OrganizerApplication,
    Participation,
    Profile,
    User,
)
from app.models.enums import ApplicationStatus, EventStatus, ParticipationState
from app.services.reference import program_title

router = APIRouter(prefix="/api/analytics", tags=["analytics"])


@router.get("/funnel")
async def funnel(
    _: RequireAdmin, session: Annotated[AsyncSession, Depends(get_session)]
) -> dict:
    books_with_demand = (
        await session.execute(
            sa.select(sa.func.count(sa.distinct(Demand.book_id))).where(
                Demand.revoked_at.is_(None)
            )
        )
    ).scalar_one()
    applications = (
        await session.execute(sa.select(sa.func.count()).select_from(OrganizerApplication))
    ).scalar_one()
    approved = (
        await session.execute(
            sa.select(sa.func.count())
            .select_from(OrganizerApplication)
            .where(OrganizerApplication.status == ApplicationStatus.APPROVED)
        )
    ).scalar_one()
    scheduled = (
        await session.execute(
            sa.select(sa.func.count())
            .select_from(Event)
            .where(Event.status.in_((EventStatus.SCHEDULED, EventStatus.HELD)))
        )
    ).scalar_one()
    held = (
        await session.execute(
            sa.select(sa.func.count()).select_from(Event).where(Event.status == EventStatus.HELD)
        )
    ).scalar_one()
    attended = (
        await session.execute(sa.select(sa.func.count()).select_from(Attendance))
    ).scalar_one()

    return {
        "books_with_demand": books_with_demand,
        "applications": applications,
        "approved": approved,
        "scheduled": scheduled,
        "held": held,
        "attendances": attended,
    }


@router.get("/unmet-demand")
async def unmet_demand(
    _: RequireAdmin,
    session: Annotated[AsyncSession, Depends(get_session)],
    limit: int = 20,
) -> list[dict]:
    """Книги, которых ждут дольше всего и по которым так и нет ведущего.

    Это главный рабочий список оргкомитета: именно отсюда берутся темы,
    под которые стоит искать организатора.
    """
    busy = sa.select(Event.book_id).where(
        Event.status.in_(
            (EventStatus.SLOT_SELECTION, EventStatus.VOTING, EventStatus.SCHEDULED)
        )
    )
    rows = await session.execute(
        sa.select(
            Book.id,
            Book.title,
            sa.func.count(Demand.id).label("waiting"),
            sa.func.min(Demand.created_at).label("since"),
        )
        .join(Demand, Demand.book_id == Book.id)
        .where(Demand.revoked_at.is_(None), Book.id.not_in(busy))
        .group_by(Book.id, Book.title)
        .order_by(sa.desc("waiting"), sa.asc("since"))
        .limit(limit)
    )
    return [
        {"book_id": book_id, "title": title, "waiting": waiting, "since": since}
        for book_id, title, waiting, since in rows
    ]


@router.get("/by-type")
async def by_type(
    _: RequireAdmin, session: Annotated[AsyncSession, Depends(get_session)]
) -> list[dict]:
    """Разрез по форматам: сколько встреч, какая явка, как их оценивают."""
    rows = await session.execute(
        sa.select(
            EventType.title,
            sa.func.count(sa.distinct(Event.id)).label("events"),
            sa.func.count(sa.distinct(Attendance.id)).label("attendances"),
            sa.func.count(sa.distinct(Participation.id))
            .filter(Participation.state == ParticipationState.GOING)
            .label("confirmed"),
            sa.func.avg(EventFeedback.score).label("avg_score"),
        )
        .join(Event, Event.event_type_id == EventType.id)
        .outerjoin(Attendance, Attendance.event_id == Event.id)
        .outerjoin(Participation, Participation.event_id == Event.id)
        .outerjoin(EventFeedback, EventFeedback.event_id == Event.id)
        .group_by(EventType.title)
        .order_by(sa.desc("events"))
    )
    return [
        {
            "type": title,
            "events": events,
            "attendances": attendances,
            "confirmed": confirmed,
            "avg_score": round(float(avg), 2) if avg is not None else None,
        }
        for title, events, attendances, confirmed, avg in rows
    ]


@router.get("/by-program")
async def by_program(
    _: RequireAdmin, session: Annotated[AsyncSession, Depends(get_session)]
) -> list[dict]:
    """Разрез по направлениям и категориям участников: кто вообще в клубе
    и кто до встреч доходит."""
    rows = await session.execute(
        sa.select(
            Profile.program,
            Profile.member_kind,
            Profile.study_level,
            sa.func.count(sa.distinct(User.id)),
            sa.func.count(sa.distinct(Attendance.id)),
        )
        .select_from(Profile)
        .join(User, User.id == Profile.user_id)
        .outerjoin(Attendance, Attendance.user_id == User.id)
        .group_by(Profile.program, Profile.member_kind, Profile.study_level)
        .order_by(sa.desc(sa.func.count(sa.distinct(User.id))))
    )
    return [
        {
            "program": program.value if program else None,
            "program_title": program_title(program.value if program else None) or "—",
            "member_kind": kind.value if kind else None,
            "study_level": level.value if level else None,
            "people": people,
            "attendances": attendances,
        }
        for program, kind, level, people, attendances in rows
    ]


@router.get("/organizers")
async def organizers(
    _: RequireAdmin, session: Annotated[AsyncSession, Depends(get_session)]
) -> list[dict]:
    rows = await session.execute(
        sa.select(
            User.display_name,
            sa.func.count(sa.distinct(Event.id)),
            sa.func.avg(EventFeedback.score),
        )
        .join(Event, Event.organizer_user_id == User.id)
        .outerjoin(EventFeedback, EventFeedback.event_id == Event.id)
        .group_by(User.display_name)
        .order_by(sa.desc(sa.func.count(sa.distinct(Event.id))))
    )
    return [
        {
            "name": name,
            "events": events,
            "avg_score": round(float(avg), 2) if avg is not None else None,
        }
        for name, events, avg in rows
    ]
