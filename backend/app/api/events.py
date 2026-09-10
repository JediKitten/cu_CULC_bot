from typing import Annotated

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import CurrentUser, RequireAdmin
from app.db import get_session
from app.models import Attendance, Event, EventFeedback, Participation, User
from app.models.enums import (
    AttendanceMethod,
    DecidedBy,
    EventStatus,
    UserRole,
)
from app.schemas import (
    AttendanceIn,
    DecideIn,
    EventOut,
    FeedbackIn,
    ParticipationIn,
    SlotsIn,
    VoteIn,
)
from app.services import eventcards
from app.services import events as service
from app.services import people as people_service

router = APIRouter(prefix="/api/events", tags=["events"])


@router.get("/{event_id}", response_model=EventOut)
async def get_event(
    event_id: int,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> EventOut:
    event = await service.require_visible(session, event_id, user)
    return await eventcards.event_out(session, event, user)


@router.post("/{event_id}/slots", response_model=EventOut)
async def publish_slots(
    event_id: int,
    body: SlotsIn,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> EventOut:
    """Организатор расставляет окна и открывает голосование."""
    event = await _mine(session, event_id, user)
    event.title = body.title or event.title
    event.description = body.description or event.description
    event.capacity = body.capacity
    if body.min_attendance:
        event.min_attendance = body.min_attendance
    await service.open_voting(
        session,
        event,
        [slot.model_dump() for slot in body.slots],
        vote_days=body.vote_days,
    )
    return await eventcards.event_out(session, event, user)


@router.post("/{event_id}/vote", response_model=EventOut)
async def vote(
    event_id: int,
    body: VoteIn,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> EventOut:
    event = await service.require_visible(session, event_id, user)
    await service.vote(session, event, user.id, body.slot_ids)
    return await eventcards.event_out(session, event, user)


@router.post("/{event_id}/decide", response_model=EventOut)
async def decide(
    event_id: int,
    body: DecideIn,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> EventOut:
    """Право вето: организатор закрепляет время, не дожидаясь дедлайна."""
    event = await _mine(session, event_id, user, allow_admin=True)
    by = DecidedBy.ORGANIZER if event.organizer_user_id == user.id else DecidedBy.ADMIN
    await service.decide(session, event, slot_id=body.slot_id, by=by, note=body.note)
    return await eventcards.event_out(session, event, user)


@router.post("/{event_id}/participation", response_model=EventOut)
async def participation(
    event_id: int,
    body: ParticipationIn,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> EventOut:
    event = await service.require_visible(session, event_id, user)
    await service.set_participation(session, event, user.id, body.state)
    return await eventcards.event_out(session, event, user)


@router.get("/{event_id}/code")
async def attendance_code(
    event_id: int,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict[str, str]:
    """Код, который организатор называет вслух на встрече."""
    event = await _mine(session, event_id, user, allow_admin=True)
    return {"code": await service.rotate_code(session, event)}


@router.post("/{event_id}/attend", response_model=EventOut)
async def attend(
    event_id: int,
    body: AttendanceIn,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> EventOut:
    event = await service.require_visible(session, event_id, user)
    code = (event.attendance_code or "").upper()
    if not code or body.code.strip().upper() != code:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Код не подошёл")
    await service.mark_attendance(session, event, user.id, AttendanceMethod.CODE)
    return await eventcards.event_out(session, event, user)


@router.post("/{event_id}/attend/{user_id}", response_model=EventOut)
async def attend_manual(
    event_id: int,
    user_id: int,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> EventOut:
    """Ручная отметка организатором — для тех, у кого не дошли руки до кода."""
    event = await _mine(session, event_id, user, allow_admin=True)
    await service.mark_attendance(
        session, event, user_id, AttendanceMethod.MANUAL, marked_by=user.id
    )
    return await eventcards.event_out(session, event, user)


@router.post("/{event_id}/feedback", response_model=EventOut)
async def feedback(
    event_id: int,
    body: FeedbackIn,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> EventOut:
    event = await service.require_visible(session, event_id, user)

    was_there = (
        await session.execute(
            sa.select(Attendance.id).where(
                Attendance.event_id == event.id, Attendance.user_id == user.id
            )
        )
    ).scalar_one_or_none() is not None
    if not was_there:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Оценить можно встречу, на которой вы были"
        )

    row = (
        await session.execute(
            sa.select(EventFeedback).where(
                EventFeedback.event_id == event.id, EventFeedback.user_id == user.id
            )
        )
    ).scalar_one_or_none()
    if row is None:
        row = EventFeedback(event_id=event.id, user_id=user.id)
        session.add(row)
    row.score = body.score
    row.text = (body.text or "").strip() or None
    await session.commit()
    return await eventcards.event_out(session, event, user)


@router.get("/{event_id}/people")
async def participants(
    event_id: int,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[dict]:
    """Кто идёт. Нужно организатору для ручной отметки присутствия.

    Функция называется participants, а не people: одноимённый модуль
    импортирован рядом, и обработчик его затенял — вызов падал в рантайме,
    а линтер молчал, потому что имя формально было определено.
    """
    event = await _mine(session, event_id, user, allow_admin=True)
    rows = await session.execute(
        sa.select(Participation.user_id, Participation.state).where(
            Participation.event_id == event.id
        )
    )
    found = list(rows)
    titles = await people_service.names(session, [user_id for user_id, _ in found])
    return sorted(
        (
            {"id": user_id, "name": titles.get(user_id, ""), "state": state.value}
            for user_id, state in found
        ),
        key=lambda row: row["name"],
    )


@router.post("/{event_id}/cancel", response_model=EventOut)
async def cancel(
    event_id: int,
    body: DecideIn | None = None,
    *,
    user: RequireAdmin,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> EventOut:
    event = await session.get(Event, event_id)
    if event is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Встреча не найдена")
    event.status = EventStatus.CANCELLED
    event.cancel_reason = (body.note if body else None) or "Без указания причины"
    await session.commit()
    return await eventcards.event_out(session, event, user)


async def _mine(
    session: AsyncSession, event_id: int, user: User, *, allow_admin: bool = False
) -> Event:
    event = await session.get(Event, event_id)
    if event is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Встреча не найдена")
    if event.organizer_user_id != user.id and not (
        allow_admin and user.role.rank >= UserRole.ADMIN.rank
    ):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Это не ваша встреча")
    return event
