"""Сборка карточек мероприятий и спроса для афиши."""

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Attendance,
    Book,
    Demand,
    DemandType,
    Event,
    EventFeedback,
    EventSlot,
    EventType,
    OrganizerApplication,
    Participation,
    Profile,
    SlotVote,
    User,
)
from app.models.enums import ApplicationStatus, EventStatus, MemberKind
from app.schemas import BookBrief, DemandCardOut, DemandTypeCount, EventOut, SlotOut
from app.services import cards
from app.services import events as events_service


async def slots_of(
    session: AsyncSession, event_id: int, user_id: int
) -> list[SlotOut]:
    counted = await events_service.tally(session, event_id)
    mine = set(
        (
            await session.execute(
                sa.select(SlotVote.slot_id).where(
                    SlotVote.event_id == event_id, SlotVote.user_id == user_id
                )
            )
        )
        .scalars()
        .all()
    )
    return [
        SlotOut(
            id=slot.id,
            starts_at=slot.starts_at,
            duration_minutes=slot.duration_minutes,
            place=slot.place,
            note=slot.note,
            votes=votes,
            my_vote=slot.id in mine,
        )
        for slot, votes in counted
    ]


async def event_out(
    session: AsyncSession, event: Event, user: User, *, with_slots: bool = True
) -> EventOut:
    book = await session.get(Book, event.book_id)
    event_type = await session.get(EventType, event.event_type_id)
    organizer = await session.get(User, event.organizer_user_id)

    slot = await session.get(EventSlot, event.slot_id) if event.slot_id else None
    participation = (
        await session.execute(
            sa.select(Participation).where(
                Participation.event_id == event.id, Participation.user_id == user.id
            )
        )
    ).scalar_one_or_none()
    attended = (
        await session.execute(
            sa.select(Attendance.id).where(
                Attendance.event_id == event.id, Attendance.user_id == user.id
            )
        )
    ).scalar_one_or_none() is not None
    feedback = (
        await session.execute(
            sa.select(EventFeedback.score).where(
                EventFeedback.event_id == event.id, EventFeedback.user_id == user.id
            )
        )
    ).scalar_one_or_none()

    return EventOut(
        id=event.id,
        book=cards.brief_from_book(book) if book else BookBrief(title="—"),
        event_type_id=event.event_type_id,
        event_type_title=event_type.title if event_type else "",
        organizer_id=event.organizer_user_id,
        organizer_name=organizer.display_name if organizer else "",
        title=event.title,
        description=event.description,
        place=slot.place if slot and slot.place else event.place,
        capacity=event.capacity,
        audience=[MemberKind(value) for value in event.audience],
        status=event.status,
        vote_deadline=event.vote_deadline,
        starts_at=slot.starts_at if slot else None,
        duration_minutes=slot.duration_minutes if slot else None,
        slots=await slots_of(session, event.id, user.id) if with_slots else [],
        going=await events_service.count_going(session, event.id),
        my_state=participation.state if participation else None,
        my_event=event.organizer_user_id == user.id,
        attended=attended,
        my_feedback_score=feedback,
        cancel_reason=event.cancel_reason,
    )


async def visible_events(
    session: AsyncSession, user: User, statuses: tuple[EventStatus, ...]
) -> list[Event]:
    """Встречи, доступные этому человеку.

    Голосующиеся идут первыми — по ним ждут действия; дальше назначенные по
    времени. Свои встречи организатора попадают сюда даже на стадии расстановки
    окон: иначе он не нашёл бы, куда вернуться.
    """
    profile = await session.get(Profile, user.id)
    stmt = (
        sa.select(Event)
        .where(Event.status.in_(statuses))
        .where(
            sa.or_(
                events_service.audience_filter(profile),
                Event.organizer_user_id == user.id,
            )
        )
        .order_by(
            sa.case((Event.status == EventStatus.VOTING, 0), else_=1),
            Event.vote_deadline.asc().nulls_last(),
            Event.id.desc(),
        )
    )
    rows = list((await session.execute(stmt)).scalars().all())

    own_pending = list(
        (
            await session.execute(
                sa.select(Event).where(
                    Event.organizer_user_id == user.id,
                    Event.status == EventStatus.SLOT_SELECTION,
                )
            )
        )
        .scalars()
        .all()
    )
    known = {event.id for event in rows}
    return [e for e in own_pending if e.id not in known] + rows


async def demand_cards(session: AsyncSession, user: User, limit: int = 50) -> list[DemandCardOut]:
    """Нижний ярус афиши: книги, по которым ждут встречу, но ведущего нет.

    Книги с уже открытым мероприятием отсюда уходят — они наверху.
    """
    busy_books = sa.select(Event.book_id).where(
        Event.status.in_(
            (EventStatus.SLOT_SELECTION, EventStatus.VOTING, EventStatus.SCHEDULED)
        )
    )
    rows = await session.execute(
        sa.select(
            Book,
            sa.func.count(Demand.id).label("waiting"),
            sa.func.count(Demand.id).filter(Demand.has_read).label("readers"),
            sa.func.max(Demand.created_at).label("last_at"),
        )
        .join(Demand, Demand.book_id == Book.id)
        .where(Demand.revoked_at.is_(None), Book.id.not_in(busy_books))
        .group_by(Book.id)
        .order_by(sa.desc("waiting"), sa.desc("last_at"))
        .limit(limit)
    )
    found = list(rows)
    book_ids = [book.id for book, *_ in found]
    if not book_ids:
        return []

    type_rows = await session.execute(
        sa.select(Demand.book_id, EventType.id, EventType.title, sa.func.count())
        .join(DemandType, DemandType.demand_id == Demand.id)
        .join(EventType, EventType.id == DemandType.event_type_id)
        .where(Demand.book_id.in_(book_ids), Demand.revoked_at.is_(None))
        .group_by(Demand.book_id, EventType.id, EventType.title)
        .order_by(sa.func.count().desc())
    )
    by_book: dict[int, list[DemandTypeCount]] = {}
    for book_id, type_id, title, count in type_rows:
        by_book.setdefault(book_id, []).append(
            DemandTypeCount(event_type_id=type_id, title=title, count=count)
        )

    mine = await cards.my_demands(session, user.id, book_ids)
    with_application = set(
        (
            await session.execute(
                sa.select(OrganizerApplication.book_id).where(
                    OrganizerApplication.book_id.in_(book_ids),
                    OrganizerApplication.status.in_(
                        (ApplicationStatus.SUBMITTED, ApplicationStatus.CHAT_OPEN)
                    ),
                )
            )
        )
        .scalars()
        .all()
    )

    briefs = await cards.decorate(
        session, user.id, [cards.brief_from_book(book) for book, *_ in found]
    )
    return [
        DemandCardOut(
            book=brief,
            waiting=waiting,
            readers=readers,
            types=by_book.get(book.id, []),
            joined=book.id in mine,
            has_application=book.id in with_application,
            last_demand_at=last_at,
        )
        for brief, (book, waiting, readers, last_at) in zip(briefs, found, strict=True)
    ]
