"""Мероприятия: окна, голосование за время, участие, присутствие.

Событие живёт от одобрения заявки до отзывов:
    slot_selection → voting → scheduled → held
                              ↘ cancelled

Фильтр аудитории — один на всё. Кто не проходит, встречу не видит нигде:
ни в афише, ни по прямой ссылке, ни в голосовании. Проверка стоит в одном
месте именно поэтому — гейт, который где-то забыли повесить, не гейт.
"""

import random
import string
from datetime import UTC, datetime, timedelta

import sqlalchemy as sa
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Attendance,
    Book,
    Demand,
    Event,
    EventSlot,
    EventType,
    Participation,
    Profile,
    SlotVote,
    User,
)
from app.models.enums import (
    AttendanceMethod,
    DecidedBy,
    EventStatus,
    NotificationKind,
    ParticipationState,
    RevokeReason,
    UserRole,
)
from app.services import notify
from app.services.settings import SettingsService

# Статусы, в которых встреча вообще показывается в афише.
LIVE_STATUSES = (EventStatus.VOTING, EventStatus.SCHEDULED)


def visible_to(event: Event, profile: Profile | None, user: User | None = None) -> bool:
    """Пускать ли человека к этой встрече.

    Пустая аудитория — «всем». Организатор и оргкомитет видят свою встречу
    всегда: иначе администратор, ограничивший встречу студентами, сам бы её
    и потерял.
    """
    if user is not None and (
        user.id == event.organizer_user_id or user.role.rank >= UserRole.ADMIN.rank
    ):
        return True
    if not event.audience:
        return True
    if profile is None:
        return False
    return profile.member_kind.value in event.audience


def audience_filter(profile: Profile | None):
    """То же правило в виде условия SQL — чтобы не тащить в память всё подряд."""
    if profile is None:
        return sa.func.cardinality(Event.audience) == 0
    return sa.or_(
        sa.func.cardinality(Event.audience) == 0,
        Event.audience.any(profile.member_kind.value),
    )


async def require_visible(
    session: AsyncSession, event_id: int, user: User
) -> Event:
    event = await session.get(Event, event_id)
    if event is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Встреча не найдена")
    profile = await session.get(Profile, user.id)
    if not visible_to(event, profile, user):
        # 404, а не 403: существование закрытой встречи — тоже информация.
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Встреча не найдена")
    return event


async def interested_users(session: AsyncSession, event: Event) -> list[int]:
    """Кого звать на голосование за время.

    Тех, кто ждал встречу по этой книге, и тех, у кого этот формат отмечен
    в анкете, — но только тех, кто проходит по аудитории.
    """
    from app.models import ProfileEventType

    by_demand = sa.select(Demand.user_id).where(
        Demand.book_id == event.book_id, Demand.revoked_at.is_(None)
    )
    by_taste = sa.select(ProfileEventType.profile_id).where(
        ProfileEventType.event_type_id == event.event_type_id
    )
    stmt = (
        sa.select(User.id)
        .join(Profile, Profile.user_id == User.id)
        .where(
            User.is_active,
            Profile.completed_at.is_not(None),
            sa.or_(User.id.in_(by_demand), User.id.in_(by_taste)),
        )
    )
    if event.audience:
        stmt = stmt.where(Profile.member_kind.in_(event.audience))
    return list((await session.execute(stmt)).scalars().all())


async def open_voting(
    session: AsyncSession,
    event: Event,
    slots: list[dict],
    *,
    vote_days: int | None = None,
) -> Event:
    """Организатор расставил окна — открываем голосование."""
    if event.status is not EventStatus.SLOT_SELECTION:
        raise HTTPException(status.HTTP_409_CONFLICT, "Окна уже опубликованы")
    if not slots:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Нужно хотя бы одно окно")

    settings = SettingsService(session)
    days = vote_days or await settings.get("vote_days")
    if event.min_attendance is None:
        event.min_attendance = await settings.get("default_min_attendance")

    for slot in slots:
        session.add(EventSlot(event_id=event.id, **slot))

    event.status = EventStatus.VOTING
    event.vote_deadline = datetime.now(UTC) + timedelta(days=days)
    event.published_at = datetime.now(UTC)
    await session.flush()

    book = await session.get(Book, event.book_id)
    event_type = await session.get(EventType, event.event_type_id)
    await notify.queue_many(
        session,
        await interested_users(session, event),
        NotificationKind.SLOT_VOTING_OPEN,
        dedup_prefix=f"voting:{event.id}",
        payload={
            "event_id": event.id,
            "book_title": book.title if book else "",
            "book_authors": ", ".join((book.authors or [])[:2]) if book else "",
            "event_type": event_type.title if event_type else "",
            "deadline": event.vote_deadline.strftime("%d.%m %H:%M"),
        },
    )
    await session.commit()
    await session.refresh(event)
    return event


async def vote(session: AsyncSession, event: Event, user_id: int, slot_ids: list[int]) -> None:
    """Голос за окна. Отмечают все подходящие, поэтому вызов заменяет прежний
    набор целиком — так снятие галочки работает само собой."""
    if event.status is not EventStatus.VOTING:
        raise HTTPException(status.HTTP_409_CONFLICT, "Голосование уже закрыто")

    valid = set(
        (
            await session.execute(
                sa.select(EventSlot.id).where(
                    EventSlot.event_id == event.id, EventSlot.id.in_(slot_ids)
                )
            )
        )
        .scalars()
        .all()
    )
    await session.execute(
        sa.delete(SlotVote).where(SlotVote.event_id == event.id, SlotVote.user_id == user_id)
    )
    for slot_id in sorted(valid):
        session.add(SlotVote(event_id=event.id, slot_id=slot_id, user_id=user_id))
    await session.commit()


async def tally(session: AsyncSession, event_id: int) -> list[tuple[EventSlot, int]]:
    """Окна с числом голосов. Порядок — как решается ничья: больше голосов,
    при равенстве раньше по времени."""
    rows = await session.execute(
        sa.select(EventSlot, sa.func.count(SlotVote.id))
        .outerjoin(SlotVote, SlotVote.slot_id == EventSlot.id)
        .where(EventSlot.event_id == event_id)
        .group_by(EventSlot.id)
        .order_by(sa.func.count(SlotVote.id).desc(), EventSlot.starts_at)
    )
    return [(slot, votes) for slot, votes in rows]


async def decide(
    session: AsyncSession,
    event: Event,
    *,
    slot_id: int | None,
    by: DecidedBy,
    note: str | None = None,
) -> Event:
    """Закрепляет время встречи.

    slot_id=None означает «взять победителя голосования» — так работает
    автомат по дедлайну. Организатор до дедлайна может назвать любое своё
    окно: он знает то, чего не знает система, — аудиторию, соведущего,
    занятость зала.
    """
    if event.status not in (EventStatus.VOTING, EventStatus.SCHEDULED):
        raise HTTPException(status.HTTP_409_CONFLICT, "Время этой встречи уже не выбирают")

    counted = await tally(session, event.id)
    if not counted:
        raise HTTPException(status.HTTP_409_CONFLICT, "Окон нет, выбирать не из чего")

    if slot_id is None:
        slot = counted[0][0]
    else:
        slot = next((s for s, _ in counted if s.id == slot_id), None)
        if slot is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Такого окна нет")

    changed = event.slot_id is not None and event.slot_id != slot.id
    event.slot_id = slot.id
    event.place = slot.place or event.place
    event.status = EventStatus.SCHEDULED
    event.decided_by = by
    event.decided_at = datetime.now(UTC)
    event.decision_note = note
    await session.flush()

    if changed:
        # Перенос сбрасывает подтверждения: «приду» относилось к другому времени.
        await session.execute(sa.delete(Participation).where(Participation.event_id == event.id))

    book = await session.get(Book, event.book_id)
    payload = {
        "event_id": event.id,
        "book_title": book.title if book else "",
        "book_authors": ", ".join((book.authors or [])[:2]) if book else "",
        "when": slot.starts_at.strftime("%d.%m %H:%M"),
        "place": slot.place or event.place or "",
    }
    await notify.queue_many(
        session,
        await interested_users(session, event),
        NotificationKind.EVENT_CHANGED if changed else NotificationKind.EVENT_SCHEDULED,
        dedup_prefix=f"{'changed' if changed else 'scheduled'}:{event.id}:{slot.id}",
        payload=payload,
    )

    # Спрос по книге закрыт: встреча назначена, ждать больше нечего.
    await session.execute(
        sa.update(Demand)
        .where(Demand.book_id == event.book_id, Demand.revoked_at.is_(None))
        .values(revoked_at=sa.func.now(), revoke_reason=RevokeReason.SCHEDULED)
    )

    await session.commit()
    await session.refresh(event)
    return event


async def set_participation(
    session: AsyncSession, event: Event, user_id: int, state: ParticipationState
) -> Participation:
    if event.status is not EventStatus.SCHEDULED:
        raise HTTPException(status.HTTP_409_CONFLICT, "Записываться пока не на что")

    row = (
        await session.execute(
            sa.select(Participation).where(
                Participation.event_id == event.id, Participation.user_id == user_id
            )
        )
    ).scalar_one_or_none()

    if state is ParticipationState.GOING and event.capacity:
        going = await count_going(session, event.id)
        already = row is not None and row.state is ParticipationState.GOING
        if not already and going >= event.capacity:
            state = ParticipationState.WAITLIST

    if row is None:
        row = Participation(event_id=event.id, user_id=user_id, state=state)
        session.add(row)
    else:
        row.state = state
        row.updated_at = datetime.now(UTC)
    await session.commit()
    await session.refresh(row)
    return row


async def count_going(session: AsyncSession, event_id: int) -> int:
    return (
        await session.execute(
            sa.select(sa.func.count()).where(
                Participation.event_id == event_id,
                Participation.state == ParticipationState.GOING,
            )
        )
    ).scalar_one()


def make_code() -> str:
    """Короткий код, который называют вслух. Без похожих символов: 0/O и 1/I
    на слух неразличимы, а вводить его будут с голоса."""
    alphabet = "".join(c for c in string.ascii_uppercase + string.digits if c not in "O0I1")
    return "".join(random.choices(alphabet, k=4))


async def rotate_code(session: AsyncSession, event: Event) -> str:
    settings = SettingsService(session)
    ttl = timedelta(minutes=await settings.get("attendance_code_ttl_minutes"))
    now = datetime.now(UTC)
    if event.attendance_code and event.code_rotated_at and now - event.code_rotated_at < ttl:
        return event.attendance_code
    event.attendance_code = make_code()
    event.code_rotated_at = now
    await session.commit()
    return event.attendance_code


async def mark_attendance(
    session: AsyncSession,
    event: Event,
    user_id: int,
    method: AttendanceMethod,
    marked_by: int | None = None,
) -> None:
    exists = (
        await session.execute(
            sa.select(Attendance.id).where(
                Attendance.event_id == event.id, Attendance.user_id == user_id
            )
        )
    ).scalar_one_or_none()
    if exists is None:
        session.add(
            Attendance(
                event_id=event.id, user_id=user_id, method=method, marked_by=marked_by
            )
        )
        await session.commit()
