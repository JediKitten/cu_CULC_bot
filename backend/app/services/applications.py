"""Заявки на организацию встречи.

Путь заявки: подана → открыта переговорка → одобрена или отклонена. Одобрение
рождает мероприятие и задаёт его аудиторию. Переговорка — тема в форуме
оргкомитета — живёт до конца встречи; отказ и отзыв заявки удаляют её сразу.
"""

from datetime import UTC, datetime

import sqlalchemy as sa
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Book, Event, EventType, OrganizerApplication, User
from app.models.enums import (
    ApplicationStatus,
    EventStatus,
    EventTypeStatus,
    MemberKind,
    NotificationKind,
    UserRole,
)
from app.services import audit, notify, rooms
from app.services.settings import SettingsService

# Небольшой опрос при подаче. Вопросы живут здесь, ответы — в JSONB заявки:
# формулировки будут меняться, и мигрировать базу ради них незачем.
SURVEY: tuple[dict, ...] = (
    {"key": "read", "title": "Вы читали эту книгу?", "type": "bool", "required": True},
    {
        "key": "experience",
        "title": "Вели встречи раньше?",
        "type": "choice",
        "options": ["Нет, впервые", "Пару раз", "Регулярно"],
        "required": True,
    },
    {
        "key": "materials",
        "title": "Что подготовите?",
        "type": "multi",
        "options": [
            "Темы для обсуждения",
            "Презентацию",
            "Раздатку",
            "Доску расследования",
            "Мастер-класс",
            "Ничего, поговорим свободно",
        ],
    },
    {"key": "guests", "title": "Сколько гостей ожидаете?", "type": "int"},
    {"key": "cohost", "title": "Нужен соведущий?", "type": "bool"},
    {
        "key": "weeks",
        "title": "В какие недели готовы провести?",
        "type": "text",
        "placeholder": "Например: конец октября, кроме сессии",
    },
    {"key": "idea", "title": "О чём будет встреча?", "type": "text", "required": True},
)

# Пока встреча в одном из этих статусов, её тема в форуме нужна.
ACTIVE_EVENT_STATUSES = (EventStatus.SLOT_SELECTION, EventStatus.VOTING, EventStatus.SCHEDULED)

REQUIRED_KEYS = tuple(q["key"] for q in SURVEY if q.get("required"))


def validate_answers(answers: dict) -> dict:
    missing = [
        next(q["title"] for q in SURVEY if q["key"] == key)
        for key in REQUIRED_KEYS
        if answers.get(key) in (None, "", [], {})
    ]
    if missing:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Не заполнено: " + "; ".join(missing)
        )
    return {q["title"]: answers.get(q["key"]) for q in SURVEY if q["key"] in answers}


async def admins(session: AsyncSession) -> list[int]:
    return list(
        (
            await session.execute(
                sa.select(User.id).where(
                    User.role.in_((UserRole.ADMIN, UserRole.SUPERADMIN)), User.is_active
                )
            )
        )
        .scalars()
        .all()
    )


async def submit(
    session: AsyncSession,
    user: User,
    *,
    book_id: int,
    event_type_id: int | None,
    proposed_type_title: str | None,
    answers: dict,
) -> OrganizerApplication:
    book = await session.get(Book, book_id)
    if book is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Книга не найдена")
    if event_type_id is None and not (proposed_type_title or "").strip():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Выберите формат встречи")
    if event_type_id is not None:
        event_type = await session.get(EventType, event_type_id)
        if event_type is None or event_type.status is not EventTypeStatus.ACTIVE:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Такого формата нет")

    open_already = (
        await session.execute(
            sa.select(OrganizerApplication).where(
                OrganizerApplication.user_id == user.id,
                OrganizerApplication.book_id == book_id,
                OrganizerApplication.status.in_(
                    (ApplicationStatus.SUBMITTED, ApplicationStatus.CHAT_OPEN)
                ),
            )
        )
    ).scalar_one_or_none()
    if open_already is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Ваша заявка по этой книге уже на рассмотрении"
        )

    application = OrganizerApplication(
        user_id=user.id,
        book_id=book_id,
        event_type_id=event_type_id,
        proposed_type_title=(proposed_type_title or "").strip() or None,
        answers=validate_answers(answers),
    )
    session.add(application)
    await session.flush()

    event_type_title = (
        (await session.get(EventType, event_type_id)).title
        if event_type_id
        else application.proposed_type_title
    )
    await notify.queue_many(
        session,
        await admins(session),
        NotificationKind.APPLICATION_SUBMITTED,
        dedup_prefix=f"application:{application.id}",
        payload={
            "application_id": application.id,
            "book_title": book.title,
            "book_authors": ", ".join((book.authors or [])[:2]),
            "event_type": event_type_title or "",
            "user_name": user.display_name,
        },
    )
    audit.log(
        session,
        actor_id=user.id,
        entity="application",
        entity_id=application.id,
        action="submit",
    )
    await session.commit()
    await session.refresh(application)

    if await SettingsService(session).get("auto_open_room"):
        # Заявка уже сохранена. Если форум недоступен, оргкомитет получил
        # уведомление, а кандидату незачем видеть ошибку вместо «заявка подана».
        try:
            await open_room(session, application, actor_id=None)
        except HTTPException:
            await session.refresh(application)
    return application


async def open_room(
    session: AsyncSession, application: OrganizerApplication, *, actor_id: int | None
) -> OrganizerApplication:
    """Заводит тему в форуме под заявку и зовёт туда кандидата.

    Открыть можно и одобренную заявку, пока её встреча жива: форум могли
    подключить позже, а тему — удалить руками.
    """
    if application.topic_id is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Тема по этой заявке уже открыта")
    if application.status is ApplicationStatus.APPROVED:
        alive = (
            await session.execute(
                sa.select(Event.id).where(
                    Event.application_id == application.id,
                    Event.status.in_(ACTIVE_EVENT_STATUSES),
                )
            )
        ).scalar_one_or_none()
        if alive is None:
            raise HTTPException(status.HTTP_409_CONFLICT, "Встреча по этой заявке уже закончилась")
    elif application.status not in (ApplicationStatus.SUBMITTED, ApplicationStatus.CHAT_OPEN):
        raise HTTPException(status.HTTP_409_CONFLICT, "Заявка уже закрыта")

    book = await session.get(Book, application.book_id)
    room = await rooms.open_topic(session, application)
    payload = {
        "application_id": application.id,
        "book_title": book.title if book else "",
        "book_authors": ", ".join((book.authors or [])[:2]) if book else "",
    }

    if room is None or application.topic_id is None:
        await notify.queue_many(
            session,
            await admins(session),
            NotificationKind.NO_FREE_ROOM,
            dedup_prefix=f"noroom:{application.id}",
            payload=payload,
        )
        await session.commit()
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Форум переговорок не подключён или у бота не хватает прав — "
            "проверьте его во вкладке «Форум».",
        )

    if application.status is ApplicationStatus.SUBMITTED:
        application.status = ApplicationStatus.CHAT_OPEN
    await notify.queue(
        session,
        application.user_id,
        NotificationKind.APPLICATION_CHAT_OPEN,
        f"chatopen:{application.id}:{application.topic_id}",
        payload
        | {
            "invite_link": application.invite_link,
            "topic_link": rooms.topic_link(room.chat_id, application.topic_id),
        },
    )
    audit.log(
        session,
        actor_id=actor_id,
        entity="application",
        entity_id=application.id,
        action="open_room",
        payload={"room_id": room.id, "topic_id": application.topic_id},
    )
    await session.commit()
    await session.refresh(application)
    return application


async def close_room(session: AsyncSession, application: OrganizerApplication) -> None:
    await rooms.close_topic(session, application)


async def approve(
    session: AsyncSession,
    application: OrganizerApplication,
    *,
    actor: User,
    audience: list[MemberKind],
    event_type_id: int | None,
    comment: str | None,
) -> Event:
    """Одобряет заявку и заводит мероприятие.

    Здесь же решается аудитория: администратор отмечает, кому встреча
    доступна. Пустой список — всем.
    """
    if application.status not in (ApplicationStatus.SUBMITTED, ApplicationStatus.CHAT_OPEN):
        raise HTTPException(status.HTTP_409_CONFLICT, "Заявка уже закрыта")

    type_id = event_type_id or application.event_type_id
    if type_id is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "У заявки свой формат — выберите, к какому его отнести, или заведите новый",
        )
    event_type = await session.get(EventType, type_id)
    if event_type is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Такого формата нет")

    application.status = ApplicationStatus.APPROVED
    application.audience = [kind.value for kind in audience]
    application.event_type_id = type_id
    application.reviewed_by = actor.id
    application.reviewed_at = datetime.now(UTC)
    application.decision_comment = comment

    event = Event(
        book_id=application.book_id,
        event_type_id=type_id,
        organizer_user_id=application.user_id,
        application_id=application.id,
        audience=list(application.audience),
        status=EventStatus.SLOT_SELECTION,
        min_attendance=await SettingsService(session).get("default_min_attendance"),
    )
    session.add(event)
    await session.flush()

    book = await session.get(Book, application.book_id)
    await notify.queue(
        session,
        application.user_id,
        NotificationKind.APPLICATION_APPROVED,
        f"approved:{application.id}",
        {
            "application_id": application.id,
            "event_id": event.id,
            "book_title": book.title if book else "",
            "book_authors": ", ".join((book.authors or [])[:2]) if book else "",
            "event_type": event_type.title,
        },
    )
    audit.log(
        session,
        actor_id=actor.id,
        entity="application",
        entity_id=application.id,
        action="approve",
        payload={"event_id": event.id, "audience": application.audience},
        comment=comment,
    )
    await session.commit()

    # Тему не трогаем: в ней ведущий с оргкомитетом и договариваются о встрече.
    await rooms.post(
        session,
        application,
        "✅ Заявка одобрена. Дальше договариваемся здесь: тема останется, "
        "пока встреча не пройдёт или не отменится.",
    )
    await session.refresh(event)
    return event


async def reject(
    session: AsyncSession, application: OrganizerApplication, *, actor: User, comment: str
) -> OrganizerApplication:
    if application.status not in (ApplicationStatus.SUBMITTED, ApplicationStatus.CHAT_OPEN):
        raise HTTPException(status.HTTP_409_CONFLICT, "Заявка уже закрыта")

    application.status = ApplicationStatus.REJECTED
    application.reviewed_by = actor.id
    application.reviewed_at = datetime.now(UTC)
    application.decision_comment = comment

    book = await session.get(Book, application.book_id)
    await notify.queue(
        session,
        application.user_id,
        NotificationKind.APPLICATION_REJECTED,
        f"rejected:{application.id}",
        {
            "application_id": application.id,
            "book_title": book.title if book else "",
            "book_authors": ", ".join((book.authors or [])[:2]) if book else "",
            "comment": comment,
        },
    )
    audit.log(
        session,
        actor_id=actor.id,
        entity="application",
        entity_id=application.id,
        action="reject",
        comment=comment,
    )
    await session.commit()
    await close_room(session, application)
    await session.refresh(application)
    return application


async def withdraw(session: AsyncSession, application: OrganizerApplication) -> None:
    if application.status not in (ApplicationStatus.SUBMITTED, ApplicationStatus.CHAT_OPEN):
        raise HTTPException(status.HTTP_409_CONFLICT, "Заявка уже закрыта")
    application.status = ApplicationStatus.WITHDRAWN
    await session.commit()
    await close_room(session, application)
