"""Фоновые задачи: автозакрепление по дедлайну и завершение встреч."""

from datetime import UTC, datetime, timedelta

import sqlalchemy as sa

from app.models import Attendance, Notification, SlotVote, User
from app.models.enums import AttendanceMethod, DecidedBy, EventStatus, NotificationKind
from app.services import jobs
from tests.test_voting import build_event


async def test_deadline_closes_voting_and_picks_the_winner(session):
    base = datetime.now(UTC) + timedelta(days=7)
    event, slots = await build_event(session, slots=[base, base + timedelta(days=1)])
    # Дедлайн уже позади: голосование пора закрывать.
    event.vote_deadline = datetime.now(UTC) - timedelta(minutes=1)

    voter = User(tg_id=8001, display_name="Голосующий")
    session.add(voter)
    await session.flush()
    session.add(SlotVote(event_id=event.id, slot_id=slots[1].id, user_id=voter.id))
    await session.commit()

    assert await jobs.close_expired_voting(session) == 1

    await session.refresh(event)
    assert event.status is EventStatus.SCHEDULED
    assert event.slot_id == slots[1].id
    assert event.decided_by is DecidedBy.AUTO


async def test_second_pass_does_not_decide_twice(session):
    """Задача выполняется много раз — второй проход обязан ничего не делать."""
    base = datetime.now(UTC) + timedelta(days=7)
    event, _ = await build_event(session, slots=[base])
    event.vote_deadline = datetime.now(UTC) - timedelta(minutes=1)
    await session.commit()

    assert await jobs.close_expired_voting(session) == 1
    assert await jobs.close_expired_voting(session) == 0


async def test_voting_without_slots_does_not_crash_the_pass(session):
    """У встречи может не оказаться окон вовсе — падать из-за этого нельзя:
    вместе с ней не закрылись бы и все остальные."""
    event, _ = await build_event(session, slots=[])
    event.vote_deadline = datetime.now(UTC) - timedelta(minutes=1)
    await session.commit()

    assert await jobs.close_expired_voting(session) == 0
    await session.refresh(event)
    assert event.status is EventStatus.VOTING


async def test_past_event_closes_and_asks_for_feedback(session):
    """Отзыв просим у тех, кто был, а не у всех записавшихся."""
    started = datetime.now(UTC) - timedelta(hours=6)
    event, slots = await build_event(session, slots=[started])
    event.status = EventStatus.SCHEDULED
    event.slot_id = slots[0].id

    visitor = User(tg_id=8101, display_name="Пришёл")
    session.add(visitor)
    await session.flush()
    session.add(
        Attendance(event_id=event.id, user_id=visitor.id, method=AttendanceMethod.CODE)
    )
    await session.commit()

    assert await jobs.close_past_events(session) == 1
    await session.refresh(event)
    assert event.status is EventStatus.HELD

    kinds = (
        (await session.execute(sa.select(Notification.kind, Notification.user_id))).all()
    )
    assert (NotificationKind.FEEDBACK_REQUEST, visitor.id) in kinds


async def test_reminders_fire_once_per_event(session):
    """dedup_key не даёт послать второе напоминание, даже если задача успела
    пройти по тому же окну дважды."""
    from app.models import Participation
    from app.models.enums import ParticipationState

    soon = datetime.now(UTC) + timedelta(hours=2)
    event, slots = await build_event(session, slots=[soon])
    event.status = EventStatus.SCHEDULED
    event.slot_id = slots[0].id

    guest = User(tg_id=8201, display_name="Придёт")
    session.add(guest)
    await session.flush()
    session.add(
        Participation(event_id=event.id, user_id=guest.id, state=ParticipationState.GOING)
    )
    await session.commit()

    first = await jobs.send_reminders(session)
    second = await jobs.send_reminders(session)

    assert first == 1
    assert second == 0
