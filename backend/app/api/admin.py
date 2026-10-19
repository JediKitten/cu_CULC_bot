"""Панель оргкомитета: модерация, встречи, форум переговорок, форматы, настройки, роли."""

from datetime import UTC, datetime, timedelta
from typing import Annotated

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import RequireAdmin, RequireModerator, RequireSuperadmin
from app.db import get_session
from app.models import (
    Book,
    BookRequest,
    Event,
    EventSlot,
    EventType,
    MeetingRoom,
    OrganizerApplication,
    Profile,
    SlotVote,
    User,
)
from app.models.enums import (
    BookStatus,
    EventTypeStatus,
    MemberKind,
    NotificationKind,
    RequestStatus,
    UserRole,
)
from app.schemas import (
    AdminEventOut,
    BookRequestOut,
    EventTypeIn,
    RoleIn,
    RoomIn,
    RoomOut,
    SettingIn,
    SettingOut,
    TopicOut,
)
from app.services import audit, cards, eventcards, notify, rooms
from app.services import events as events_service
from app.services import people as people_service
from app.services.applications import ACTIVE_EVENT_STATUSES
from app.services.books.normalize import dedup_key
from app.services.settings import REGISTRY, SettingsError, SettingsService

router = APIRouter(prefix="/api/admin", tags=["admin"])


# --- Заявки на книги ---------------------------------------------------------


@router.get("/book-requests", response_model=list[BookRequestOut])
async def book_requests(
    _: RequireModerator,
    session: Annotated[AsyncSession, Depends(get_session)],
    pending_only: bool = True,
) -> list[BookRequestOut]:
    stmt = sa.select(BookRequest, User).join(User, User.id == BookRequest.user_id)
    if pending_only:
        stmt = stmt.where(BookRequest.status == RequestStatus.PENDING)
    rows = await session.execute(stmt.order_by(BookRequest.id.desc()))
    return [
        BookRequestOut(
            id=request.id,
            title=request.title,
            authors=list(request.authors or []),
            year=request.year,
            status=request.status,
            book_id=request.book_id,
            created_at=request.created_at,
            user_id=request.user_id,
            user_name=user.display_name,
            decision_comment=request.decision_comment,
        )
        for request, user in rows
    ]


@router.post("/book-requests/{request_id}/approve", status_code=204)
async def approve_book(
    request_id: int,
    actor: RequireModerator,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> None:
    request = await session.get(BookRequest, request_id)
    if request is None or request.status is not RequestStatus.PENDING:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Заявка не найдена")

    book = Book(
        title=request.title,
        authors=list(request.authors or []),
        year=request.year,
        isbn13=request.isbn13,
        cover_url=request.cover_url,
        description=request.description,
        dedup_key=dedup_key(request.title, list(request.authors or [])),
        added_by_user_id=request.user_id,
    )
    session.add(book)
    await session.flush()

    request.status = RequestStatus.APPROVED
    request.book_id = book.id
    request.reviewed_by = actor.id
    request.reviewed_at = datetime.now(UTC)
    await notify.queue(
        session,
        request.user_id,
        NotificationKind.BOOK_REQUEST_DECIDED,
        f"bookreq:{request.id}",
        {"book_title": book.title, "approved": True},
    )
    audit.log(
        session,
        actor_id=actor.id,
        entity="book_request",
        entity_id=request.id,
        action="approve",
    )
    await session.commit()


@router.post("/book-requests/{request_id}/reject", status_code=204)
async def reject_book(
    request_id: int,
    body: SettingIn,
    actor: RequireModerator,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> None:
    request = await session.get(BookRequest, request_id)
    if request is None or request.status is not RequestStatus.PENDING:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Заявка не найдена")
    comment = str(body.value or "").strip() or None
    request.status = RequestStatus.REJECTED
    request.reviewed_by = actor.id
    request.reviewed_at = datetime.now(UTC)
    request.decision_comment = comment
    await notify.queue(
        session,
        request.user_id,
        NotificationKind.BOOK_REQUEST_DECIDED,
        f"bookreq:{request.id}",
        {"book_title": request.title, "approved": False, "comment": comment},
    )
    await session.commit()


@router.post("/books/{book_id}/hide", status_code=204)
async def hide_book(
    book_id: int,
    actor: RequireModerator,
    session: Annotated[AsyncSession, Depends(get_session)],
    hidden: bool = True,
) -> None:
    book = await session.get(Book, book_id)
    if book is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Книга не найдена")
    book.status = BookStatus.HIDDEN if hidden else BookStatus.ACTIVE
    audit.log(
        session,
        actor_id=actor.id,
        entity="book",
        entity_id=book.id,
        action="hide" if hidden else "unhide",
    )
    await session.commit()


# --- Форматы встреч ----------------------------------------------------------


@router.get("/event-types")
async def event_types(
    _: RequireAdmin, session: Annotated[AsyncSession, Depends(get_session)]
) -> list[dict]:
    rows = (
        await session.execute(
            sa.select(EventType).order_by(EventType.sort_order, EventType.id)
        )
    ).scalars()
    return [
        {
            "id": row.id,
            "slug": row.slug,
            "title": row.title,
            "description": row.description,
            "requires_reading": row.requires_reading,
            "status": row.status.value,
            "is_builtin": row.is_builtin,
        }
        for row in rows
    ]


@router.post("/event-types", status_code=201)
async def create_event_type(
    body: EventTypeIn,
    actor: RequireAdmin,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    slug = f"custom-{int(datetime.now(UTC).timestamp())}"
    event_type = EventType(
        slug=slug,
        title=body.title.strip(),
        description=body.description,
        requires_reading=body.requires_reading,
        status=EventTypeStatus.ACTIVE,
        created_by_user_id=actor.id,
        sort_order=body.sort_order or 200,
    )
    session.add(event_type)
    await session.commit()
    await session.refresh(event_type)
    return {"id": event_type.id, "slug": event_type.slug, "title": event_type.title}


@router.patch("/event-types/{type_id}", status_code=204)
async def update_event_type(
    type_id: int,
    body: EventTypeIn,
    _: RequireAdmin,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> None:
    event_type = await session.get(EventType, type_id)
    if event_type is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Формат не найден")
    event_type.title = body.title.strip()
    event_type.description = body.description
    event_type.requires_reading = body.requires_reading
    if body.status:
        event_type.status = EventTypeStatus(body.status)
    if body.sort_order is not None:
        event_type.sort_order = body.sort_order
    await session.commit()


# --- Форум переговорок -------------------------------------------------------


@router.get("/rooms", response_model=list[RoomOut])
async def listing_rooms(
    _: RequireAdmin, session: Annotated[AsyncSession, Depends(get_session)]
) -> list[RoomOut]:
    topics = dict(
        (
            await session.execute(
                sa.select(OrganizerApplication.room_id, sa.func.count())
                .where(OrganizerApplication.topic_id.is_not(None))
                .group_by(OrganizerApplication.room_id)
            )
        ).all()
    )
    rows = (
        await session.execute(sa.select(MeetingRoom).order_by(MeetingRoom.id.desc()))
    ).scalars()
    return [_room_out(room, topics.get(room.id, 0)) for room in rows]


def _room_out(room: MeetingRoom, topics: int = 0) -> RoomOut:
    return RoomOut(
        id=room.id,
        chat_id=room.chat_id,
        title=room.title,
        status=room.status,
        topics=topics,
        checked_at=room.checked_at,
        check_error=room.check_error,
    )


@router.post("/rooms", response_model=RoomOut)
async def add_room(
    body: RoomIn,
    actor: RequireAdmin,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> RoomOut:
    """Подключить форум.

    Группу создаёт человек — бот этого не умеет. Здесь мы проверяем, что в ней
    включены темы, а бот администратор с нужными правами, и только тогда
    заводим запись.
    """
    try:
        room = await rooms.register(session, body.chat_id, body.title, actor.id)
    except rooms.RoomNotReady as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return _room_out(room)


@router.delete("/rooms/{room_id}", status_code=204)
async def delete_room(
    room_id: int,
    actor: RequireAdmin,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> None:
    """Отключить форум. Сама группа и темы остаются: бот из неё не выходит,
    система просто перестаёт ею распоряжаться."""
    room = await session.get(MeetingRoom, room_id)
    if room is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Форум не найден")
    audit.log(
        session,
        actor_id=actor.id,
        entity="meeting_room",
        entity_id=room.id,
        action="forget",
        payload={"chat_id": room.chat_id},
    )
    await rooms.forget(session, room)


@router.post("/rooms/{room_id}/check", status_code=204)
async def check_room(
    room_id: int,
    _: RequireAdmin,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> None:
    room = await session.get(MeetingRoom, room_id)
    if room is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Форум не найден")
    await rooms.check(session, room)


@router.get("/topics", response_model=list[TopicOut])
async def listing_topics(
    _: RequireAdmin, session: Annotated[AsyncSession, Depends(get_session)]
) -> list[TopicOut]:
    """Живые темы форума — чтобы видеть, что в нём сейчас обсуждается."""
    rows = (
        await session.execute(
            sa.select(OrganizerApplication, MeetingRoom.chat_id, Event.id, Event.status)
            .join(MeetingRoom, MeetingRoom.id == OrganizerApplication.room_id)
            .outerjoin(Event, Event.application_id == OrganizerApplication.id)
            .where(OrganizerApplication.topic_id.is_not(None))
            .order_by(OrganizerApplication.id.desc())
        )
    ).all()
    result = []
    for application, chat_id, event_id, event_status in rows:
        book = await session.get(Book, application.book_id)
        result.append(
            TopicOut(
                application_id=application.id,
                book=cards.brief_from_book(book),
                user_name=await people_service.name_of(session, application.user_id),
                application_status=application.status,
                event_id=event_id,
                event_status=event_status,
                link=rooms.topic_link(chat_id, application.topic_id),
            )
        )
    return result


# --- Встречи -----------------------------------------------------------------


@router.get("/events", response_model=list[AdminEventOut])
async def listing_events(
    _: RequireAdmin, session: Annotated[AsyncSession, Depends(get_session)]
) -> list[AdminEventOut]:
    """Все встречи для оргкомитета — без фильтра аудитории.

    Живые целиком, прошедшие и отменённые — за последний месяц: их смотрят,
    чтобы вспомнить, что было, а не чтобы управлять.
    """
    month_ago = datetime.now(UTC) - timedelta(days=30)
    events = (
        (
            await session.execute(
                sa.select(Event)
                .outerjoin(EventSlot, EventSlot.id == Event.slot_id)
                .where(
                    sa.or_(
                        Event.status.in_(ACTIVE_EVENT_STATUSES),
                        sa.func.coalesce(EventSlot.starts_at, Event.created_at) >= month_ago,
                    )
                )
                .order_by(Event.id.desc())
            )
        )
        .scalars()
        .all()
    )

    result = []
    for event in events:
        book = await session.get(Book, event.book_id)
        event_type = await session.get(EventType, event.event_type_id)
        organizer = await session.get(User, event.organizer_user_id)
        slot = await session.get(EventSlot, event.slot_id) if event.slot_id else None
        voters = (
            await session.execute(
                sa.select(sa.func.count(sa.distinct(SlotVote.user_id))).where(
                    SlotVote.event_id == event.id
                )
            )
        ).scalar_one()
        result.append(
            AdminEventOut(
                id=event.id,
                book=cards.brief_from_book(book),
                event_type_title=event_type.title if event_type else "",
                organizer_id=event.organizer_user_id,
                organizer_name=await people_service.name_of(session, event.organizer_user_id),
                organizer_username=organizer.tg_username if organizer else None,
                status=event.status,
                audience=[MemberKind(value) for value in event.audience],
                vote_deadline=event.vote_deadline,
                starts_at=slot.starts_at if slot else None,
                going=await events_service.count_going(session, event.id),
                voters=voters,
                application_id=event.application_id,
                topic_link=await eventcards.topic_link_of(session, event.application_id),
                cancel_reason=event.cancel_reason,
            )
        )
    return result


# --- Настройки и роли --------------------------------------------------------


@router.get("/settings", response_model=list[SettingOut])
async def get_settings(
    _: RequireAdmin, session: Annotated[AsyncSession, Depends(get_session)]
) -> list[SettingOut]:
    values = await SettingsService(session).all()
    return [
        SettingOut(key=spec.key, value=values[spec.key], title=spec.label, hint=spec.help)
        for spec in REGISTRY
    ]


@router.put("/settings")
async def put_settings(
    body: dict,
    actor: RequireSuperadmin,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    try:
        return await SettingsService(session).set_many(body, actor.id)
    except SettingsError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc


@router.get("/people")
async def people(
    _: RequireAdmin, session: Annotated[AsyncSession, Depends(get_session)]
) -> list[dict]:
    rows = (
        await session.execute(
            sa.select(User, Profile.full_name)
            .outerjoin(Profile, Profile.user_id == User.id)
            .order_by(sa.func.coalesce(Profile.full_name, User.display_name))
        )
    ).all()
    return [
        {
            "id": user.id,
            "name": full_name or user.display_name,
            "username": user.tg_username,
            "role": user.role.value,
        }
        for user, full_name in rows
    ]


@router.post("/roles", status_code=204)
async def set_role(
    body: RoleIn,
    actor: RequireSuperadmin,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> None:
    user = await session.get(User, body.user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Участник не найден")
    if user.id == actor.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Свою роль менять нельзя")

    previous = user.role
    user.role = body.role
    if body.role.rank > previous.rank:
        titles = {
            UserRole.MODERATOR: "модератор",
            UserRole.ADMIN: "администратор",
            UserRole.SUPERADMIN: "главный администратор",
        }
        await notify.queue(
            session,
            user.id,
            NotificationKind.ROLE_GRANTED,
            f"role:{user.id}:{body.role.value}",
            {"role_title": titles.get(body.role, body.role.value)},
        )
    audit.log(
        session,
        actor_id=actor.id,
        entity="user",
        entity_id=user.id,
        action="set_role",
        payload={"from": previous.value, "to": body.role.value},
    )
    await session.commit()
