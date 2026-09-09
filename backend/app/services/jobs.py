"""Фоновые задачи: дедлайны, напоминания, завершение встреч.

Все они выполняются много раз и обязаны быть идемпотентными: повторный проход
не должен ни закреплять время дважды, ни слать второе напоминание. За второе
отвечает dedup_key уведомления, за первое — проверка статуса встречи.
"""

import logging
from datetime import UTC, datetime, timedelta

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Attendance, Book, Event, EventSlot, Participation, User
from app.models.enums import (
    DecidedBy,
    EventStatus,
    NotificationKind,
    ParticipationState,
    UserRole,
)
from app.services import events as events_service
from app.services import notify
from app.services.settings import SettingsService

logger = logging.getLogger(__name__)

# Окно допуска для напоминаний: задача ходит раз в пять минут, полчаса с
# запасом покрывают любой пропуск, а dedup_key не даёт послать второе.
WINDOW = timedelta(minutes=30)


async def close_expired_voting(session: AsyncSession) -> int:
    """Закрепляет время у встреч, где голосование кончилось.

    Организатор мог сделать это раньше сам — тогда встреча уже не в voting
    и сюда не попадёт.
    """
    rows = (
        await session.execute(
            sa.select(Event).where(
                Event.status == EventStatus.VOTING,
                Event.vote_deadline.is_not(None),
                Event.vote_deadline <= sa.func.now(),
            )
        )
    ).scalars()

    closed = 0
    for event in list(rows):
        try:
            await events_service.decide(session, event, slot_id=None, by=DecidedBy.AUTO)
            closed += 1
        except Exception as exc:  # окон могло не оказаться вовсе
            logger.warning("Не удалось закрыть голосование %s: %s", event.id, exc)
            await session.rollback()
    return closed


async def _scheduled_with_time(session: AsyncSession) -> list[tuple[Event, EventSlot, Book | None]]:
    rows = await session.execute(
        sa.select(Event, EventSlot, Book)
        .join(EventSlot, EventSlot.id == Event.slot_id)
        .outerjoin(Book, Book.id == Event.book_id)
        .where(Event.status == EventStatus.SCHEDULED)
    )
    return list(rows)


def _payload(event: Event, slot: EventSlot, book: Book | None) -> dict:
    return {
        "event_id": event.id,
        "book_title": book.title if book else "",
        "book_authors": ", ".join((book.authors or [])[:2]) if book else "",
        "when": slot.starts_at.strftime("%d.%m %H:%M"),
        "place": slot.place or event.place or "",
    }


async def send_reminders(session: AsyncSession) -> int:
    """Напоминания за сутки и за два часа — тем, кто сказал «приду»."""
    now = datetime.now(UTC)
    sent = 0
    for event, slot, book in await _scheduled_with_time(session):
        for kind, ahead in (
            (NotificationKind.REMINDER_24H, timedelta(hours=24)),
            (NotificationKind.REMINDER_2H, timedelta(hours=2)),
        ):
            target = slot.starts_at - ahead
            if not (target <= now <= target + WINDOW):
                continue
            going = (
                (
                    await session.execute(
                        sa.select(Participation.user_id).where(
                            Participation.event_id == event.id,
                            Participation.state == ParticipationState.GOING,
                        )
                    )
                )
                .scalars()
                .all()
            )
            sent += await notify.queue_many(
                session,
                list(going),
                kind,
                dedup_prefix=f"{kind.value}:{event.id}",
                payload=_payload(event, slot, book),
            )
    await session.commit()
    return sent


async def warn_low_attendance(session: AsyncSession) -> int:
    """Предупреждение о недоборе — за сутки до встречи.

    Решение о проведении всё равно за организатором: система не отменяет
    встречи сама, она только показывает цифры вовремя.
    """
    now = datetime.now(UTC)
    settings = SettingsService(session)
    default_quorum = await settings.get("default_min_attendance")
    sent = 0

    for event, slot, book in await _scheduled_with_time(session):
        target = slot.starts_at - timedelta(hours=24)
        if not (target <= now <= target + WINDOW):
            continue
        quorum = event.min_attendance or default_quorum
        going = await events_service.count_going(session, event.id)
        if going >= quorum:
            continue

        admins = (
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
        sent += await notify.queue_many(
            session,
            [event.organizer_user_id, *admins],
            NotificationKind.LOW_ATTENDANCE,
            dedup_prefix=f"lowatt:{event.id}",
            payload=_payload(event, slot, book) | {"going": going, "quorum": quorum},
        )
    await session.commit()
    return sent


async def close_past_events(session: AsyncSession) -> int:
    """Переводит прошедшие встречи в «состоялась» и просит отзыв у тех, кто был."""
    now = datetime.now(UTC)
    settings = SettingsService(session)
    delay = timedelta(hours=await settings.get("feedback_delay_hours"))
    closed = 0

    for event, slot, book in await _scheduled_with_time(session):
        ends_at = slot.starts_at + timedelta(minutes=slot.duration_minutes)
        if now < ends_at + delay:
            continue

        event.status = EventStatus.HELD
        attended = (
            (
                await session.execute(
                    sa.select(Attendance.user_id).where(Attendance.event_id == event.id)
                )
            )
            .scalars()
            .all()
        )
        await notify.queue_many(
            session,
            list(attended),
            NotificationKind.FEEDBACK_REQUEST,
            dedup_prefix=f"feedback:{event.id}",
            payload=_payload(event, slot, book),
        )
        closed += 1

    await session.commit()
    return closed


async def run_all(session: AsyncSession) -> dict[str, int]:
    return {
        "voting_closed": await close_expired_voting(session),
        "reminders": await send_reminders(session),
        "low_attendance": await warn_low_attendance(session),
        "events_closed": await close_past_events(session),
    }
