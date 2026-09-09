from typing import Annotated

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import CurrentUser, RequireAdmin
from app.db import get_session
from app.models import Book, Event, EventType, MeetingRoom, OrganizerApplication, User
from app.models.enums import ApplicationStatus, MemberKind
from app.schemas import ApplicationIn, ApplicationOut, ApproveIn, RejectIn
from app.services import applications as service
from app.services import cards

router = APIRouter(prefix="/api/applications", tags=["applications"])


@router.get("/survey")
async def survey(_: CurrentUser) -> list[dict]:
    """Вопросы опроса. Отдаются с сервера, чтобы формулировки правились
    в одном месте, а не в двух."""
    return [dict(question) for question in service.SURVEY]


@router.post("", response_model=ApplicationOut)
async def submit(
    body: ApplicationIn,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ApplicationOut:
    application = await service.submit(
        session,
        user,
        book_id=body.book_id,
        event_type_id=body.event_type_id,
        proposed_type_title=body.proposed_type_title,
        answers=body.answers,
    )
    return await out(session, application)


@router.get("/mine", response_model=list[ApplicationOut])
async def mine(
    user: CurrentUser, session: Annotated[AsyncSession, Depends(get_session)]
) -> list[ApplicationOut]:
    rows = (
        await session.execute(
            sa.select(OrganizerApplication)
            .where(OrganizerApplication.user_id == user.id)
            .order_by(OrganizerApplication.id.desc())
        )
    ).scalars()
    return [await out(session, row) for row in rows]


@router.post("/{application_id}/withdraw", status_code=204)
async def withdraw(
    application_id: int,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> None:
    application = await _get(session, application_id)
    if application.user_id != user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Это не ваша заявка")
    await service.withdraw(session, application)


# --- Оргкомитет --------------------------------------------------------------


@router.get("", response_model=list[ApplicationOut])
async def listing(
    _: RequireAdmin,
    session: Annotated[AsyncSession, Depends(get_session)],
    open_only: bool = True,
) -> list[ApplicationOut]:
    stmt = sa.select(OrganizerApplication).order_by(OrganizerApplication.id.desc())
    if open_only:
        stmt = stmt.where(
            OrganizerApplication.status.in_(
                (ApplicationStatus.SUBMITTED, ApplicationStatus.CHAT_OPEN)
            )
        )
    rows = (await session.execute(stmt)).scalars()
    return [await out(session, row) for row in rows]


@router.post("/{application_id}/open-room", response_model=ApplicationOut)
async def open_room(
    application_id: int,
    actor: RequireAdmin,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ApplicationOut:
    application = await _get(session, application_id)
    await service.open_room(session, application, actor_id=actor.id)
    return await out(session, application)


@router.post("/{application_id}/approve", response_model=ApplicationOut)
async def approve(
    application_id: int,
    body: ApproveIn,
    actor: RequireAdmin,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ApplicationOut:
    application = await _get(session, application_id)
    await service.approve(
        session,
        application,
        actor=actor,
        audience=body.audience,
        event_type_id=body.event_type_id,
        comment=body.comment,
    )
    return await out(session, application)


@router.post("/{application_id}/reject", response_model=ApplicationOut)
async def reject(
    application_id: int,
    body: RejectIn,
    actor: RequireAdmin,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ApplicationOut:
    application = await _get(session, application_id)
    await service.reject(session, application, actor=actor, comment=body.comment)
    return await out(session, application)


async def _get(session: AsyncSession, application_id: int) -> OrganizerApplication:
    application = await session.get(OrganizerApplication, application_id)
    if application is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Заявка не найдена")
    return application


async def out(session: AsyncSession, application: OrganizerApplication) -> ApplicationOut:
    book = await session.get(Book, application.book_id)
    user = await session.get(User, application.user_id)
    event_type = (
        await session.get(EventType, application.event_type_id)
        if application.event_type_id
        else None
    )
    room = await session.get(MeetingRoom, application.room_id) if application.room_id else None
    event_id = (
        await session.execute(
            sa.select(Event.id).where(Event.application_id == application.id).limit(1)
        )
    ).scalar_one_or_none()

    return ApplicationOut(
        id=application.id,
        book=cards.brief_from_book(book) if book else None,
        user_id=application.user_id,
        user_name=user.display_name if user else "",
        user_username=user.tg_username if user else None,
        event_type_id=application.event_type_id,
        event_type_title=event_type.title if event_type else None,
        proposed_type_title=application.proposed_type_title,
        answers=application.answers or {},
        status=application.status,
        audience=[MemberKind(value) for value in application.audience],
        room_title=room.title if room else None,
        invite_link=application.invite_link,
        decision_comment=application.decision_comment,
        created_at=application.created_at,
        event_id=event_id,
    )
