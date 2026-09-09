"""Панель оргкомитета: модерация, переговорки, форматы, настройки, роли."""

from datetime import UTC, datetime
from typing import Annotated

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import RequireAdmin, RequireModerator, RequireSuperadmin
from app.db import get_session
from app.models import Book, BookRequest, EventType, MeetingRoom, User
from app.models.enums import (
    BookStatus,
    EventTypeStatus,
    NotificationKind,
    RequestStatus,
    RoomStatus,
    UserRole,
)
from app.schemas import (
    BookRequestOut,
    EventTypeIn,
    RoleIn,
    RoomIn,
    RoomOut,
    SettingIn,
    SettingOut,
)
from app.services import audit, notify, rooms
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


# --- Переговорки -------------------------------------------------------------


@router.get("/rooms", response_model=list[RoomOut])
async def listing_rooms(
    _: RequireAdmin, session: Annotated[AsyncSession, Depends(get_session)]
) -> list[RoomOut]:
    rows = (
        await session.execute(sa.select(MeetingRoom).order_by(MeetingRoom.id))
    ).scalars()
    return [
        RoomOut(
            id=room.id,
            chat_id=room.chat_id,
            title=room.title,
            status=room.status,
            application_id=room.current_application_id,
            checked_at=room.checked_at,
            check_error=room.check_error,
        )
        for room in rows
    ]


@router.post("/rooms", response_model=RoomOut)
async def add_room(
    body: RoomIn,
    actor: RequireAdmin,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> RoomOut:
    """Добавить чат в пул. Чат создаёт человек — бот этого не умеет; здесь мы
    только проверяем, что бот в нём администратор с нужными правами."""
    room = await rooms.register(session, body.chat_id, body.title, actor.id)
    return RoomOut(
        id=room.id,
        chat_id=room.chat_id,
        title=room.title,
        status=room.status,
        application_id=room.current_application_id,
        checked_at=room.checked_at,
        check_error=room.check_error,
    )


@router.post("/rooms/{room_id}/check", status_code=204)
async def check_room(
    room_id: int,
    _: RequireAdmin,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> None:
    room = await session.get(MeetingRoom, room_id)
    if room is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Комната не найдена")
    await rooms.check(session, room)


@router.post("/rooms/{room_id}/release", status_code=204)
async def release_room(
    room_id: int,
    _: RequireAdmin,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> None:
    """Принудительно освободить комнату — когда заявка зависла."""
    room = await session.get(MeetingRoom, room_id)
    if room is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Комната не найдена")
    await rooms.release(session, room, kick_user_tg_id=None)


@router.post("/rooms/{room_id}/disable", status_code=204)
async def disable_room(
    room_id: int,
    _: RequireAdmin,
    session: Annotated[AsyncSession, Depends(get_session)],
    disabled: bool = True,
) -> None:
    room = await session.get(MeetingRoom, room_id)
    if room is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Комната не найдена")
    room.status = RoomStatus.DISABLED if disabled else RoomStatus.FREE
    await session.commit()


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
        await session.execute(sa.select(User).order_by(User.display_name))
    ).scalars()
    return [
        {
            "id": user.id,
            "name": user.display_name,
            "username": user.tg_username,
            "role": user.role.value,
        }
        for user in rows
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
