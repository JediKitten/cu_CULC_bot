"""Подсчёт голосов и закрепление времени."""

from datetime import UTC, datetime, timedelta

import sqlalchemy as sa

from app.models import Event, EventSlot, EventType, SlotVote, User
from app.models.enums import DecidedBy, EventStatus
from app.services import events as service
from tests.test_flow import make_book


async def build_event(session, *, slots: list[datetime]) -> tuple[Event, list[EventSlot]]:
    book = await make_book(session, "Град обречённый", ["Стругацкие"])
    organizer = User(tg_id=9001, display_name="Ведущий")
    session.add(organizer)
    await session.flush()

    event_type_id = (
        await session.execute(sa.select(EventType.id).order_by(EventType.id).limit(1))
    ).scalar_one()

    event = Event(
        book_id=book.id,
        event_type_id=event_type_id,
        organizer_user_id=organizer.id,
        status=EventStatus.VOTING,
        vote_deadline=datetime.now(UTC) + timedelta(days=1),
    )
    session.add(event)
    await session.flush()

    rows = [EventSlot(event_id=event.id, starts_at=starts_at) for starts_at in slots]
    session.add_all(rows)
    await session.commit()
    return event, rows


async def vote(session, event: Event, slot: EventSlot, tg_id: int) -> None:
    user = User(tg_id=tg_id, display_name=f"Голос {tg_id}")
    session.add(user)
    await session.flush()
    session.add(SlotVote(event_id=event.id, slot_id=slot.id, user_id=user.id))
    await session.commit()


async def test_winner_is_the_most_voted(session):
    base = datetime(2026, 10, 1, 18, tzinfo=UTC)
    event, slots = await build_event(session, slots=[base, base + timedelta(days=2)])

    await vote(session, event, slots[1], 9101)
    await vote(session, event, slots[1], 9102)
    await vote(session, event, slots[0], 9103)

    decided = await service.decide(session, event, slot_id=None, by=DecidedBy.AUTO)

    assert decided.slot_id == slots[1].id
    assert decided.status is EventStatus.SCHEDULED
    assert decided.decided_by is DecidedBy.AUTO


async def test_tie_goes_to_the_earlier_slot(session):
    base = datetime(2026, 10, 1, 18, tzinfo=UTC)
    event, slots = await build_event(session, slots=[base, base + timedelta(days=2)])

    await vote(session, event, slots[0], 9201)
    await vote(session, event, slots[1], 9202)

    decided = await service.decide(session, event, slot_id=None, by=DecidedBy.AUTO)

    assert decided.slot_id == slots[0].id


async def test_organizer_veto_beats_the_count(session):
    """Организатор знает то, чего не знает система: зал, соведущего, экзамены."""
    base = datetime(2026, 10, 1, 18, tzinfo=UTC)
    event, slots = await build_event(session, slots=[base, base + timedelta(days=2)])

    await vote(session, event, slots[1], 9301)
    await vote(session, event, slots[1], 9302)

    decided = await service.decide(
        session, event, slot_id=slots[0].id, by=DecidedBy.ORGANIZER, note="Зал занят"
    )

    assert decided.slot_id == slots[0].id
    assert decided.decided_by is DecidedBy.ORGANIZER
    assert decided.decision_note == "Зал занят"


async def test_voting_twice_replaces_the_previous_choice(session):
    """Голосуют галочками, поэтому вызов заменяет набор целиком — иначе снятая
    галочка не снималась бы."""
    base = datetime(2026, 10, 1, 18, tzinfo=UTC)
    event, slots = await build_event(session, slots=[base, base + timedelta(days=2)])

    user = User(tg_id=9401, display_name="Переменчивый")
    session.add(user)
    await session.flush()
    await session.commit()

    await service.vote(session, event, user.id, [slots[0].id, slots[1].id])
    assert [votes for _, votes in await service.tally(session, event.id)] == [1, 1]

    await service.vote(session, event, user.id, [slots[1].id])
    counted = {slot.id: votes for slot, votes in await service.tally(session, event.id)}
    assert counted[slots[0].id] == 0
    assert counted[slots[1].id] == 1


async def test_reschedule_drops_confirmations(session):
    """Перенос сбрасывает «приду»: подтверждение относилось к другому времени."""
    from app.models import Participation
    from app.models.enums import ParticipationState

    base = datetime(2026, 10, 1, 18, tzinfo=UTC)
    event, slots = await build_event(session, slots=[base, base + timedelta(days=2)])
    await service.decide(session, event, slot_id=slots[0].id, by=DecidedBy.ORGANIZER)

    guest = User(tg_id=9501, display_name="Придёт")
    session.add(guest)
    await session.flush()
    session.add(
        Participation(event_id=event.id, user_id=guest.id, state=ParticipationState.GOING)
    )
    await session.commit()
    assert await service.count_going(session, event.id) == 1

    await service.decide(session, event, slot_id=slots[1].id, by=DecidedBy.ORGANIZER)
    assert await service.count_going(session, event.id) == 0
