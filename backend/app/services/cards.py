"""Сборка карточек книг для интерфейса.

Список и карточка отдаются с состоянием текущего пользователя внутри — читал
ли он книгу, ждёт ли встречу, — чтобы клиент рисовал строку одним ответом,
а не дозапрашивал состояние для каждой из двадцати книг.
"""

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Book, Demand, DemandType, EventType, ReadingEntry
from app.models.enums import ApplicationStatus, EventStatus, ReadingStatus
from app.models.event import Event
from app.models.organizing import OrganizerApplication
from app.schemas import BookBrief, BookCard, DemandTypeCount
from app.services.books.normalize import BookCandidate


async def demand_counts(session: AsyncSession, book_ids: list[int]) -> dict[int, tuple[int, int]]:
    """{book_id: (сколько ждут, из них читали)} по активным отметкам."""
    if not book_ids:
        return {}
    rows = await session.execute(
        sa.select(
            Demand.book_id,
            sa.func.count().label("waiting"),
            sa.func.count().filter(Demand.has_read).label("readers"),
        )
        .where(Demand.book_id.in_(book_ids), Demand.revoked_at.is_(None))
        .group_by(Demand.book_id)
    )
    return {book_id: (waiting, readers) for book_id, waiting, readers in rows}


async def my_entries(
    session: AsyncSession, user_id: int, book_ids: list[int]
) -> dict[int, ReadingEntry]:
    if not book_ids:
        return {}
    rows = (
        await session.execute(
            sa.select(ReadingEntry).where(
                ReadingEntry.user_id == user_id, ReadingEntry.book_id.in_(book_ids)
            )
        )
    ).scalars()
    return {entry.book_id: entry for entry in rows}


async def my_demands(session: AsyncSession, user_id: int, book_ids: list[int]) -> set[int]:
    if not book_ids:
        return set()
    rows = (
        await session.execute(
            sa.select(Demand.book_id).where(
                Demand.user_id == user_id,
                Demand.book_id.in_(book_ids),
                Demand.revoked_at.is_(None),
            )
        )
    ).scalars()
    return set(rows)


async def favourites(session: AsyncSession, user_id: int) -> list[BookBrief]:
    """Витрина профиля: до четырёх книг в выбранном человеком порядке."""
    rows = (
        await session.execute(
            sa.select(Book, ReadingEntry.favourite_position)
            .join(ReadingEntry, ReadingEntry.book_id == Book.id)
            .where(
                ReadingEntry.user_id == user_id,
                ReadingEntry.favourite_position.is_not(None),
            )
            .order_by(ReadingEntry.favourite_position)
        )
    ).all()
    return [
        BookBrief(**brief_from_book(book).model_dump() | {"favourite_position": position})
        for book, position in rows
    ]


def brief_from_book(book: Book) -> BookBrief:
    return BookBrief(
        id=book.id,
        title=book.title,
        authors=list(book.authors or []),
        year=book.year,
        cover_url=book.cover_url,
    )


def brief_from_candidate(candidate: BookCandidate) -> BookBrief:
    return BookBrief(
        id=candidate.book_id,
        title=candidate.title,
        authors=candidate.authors,
        year=candidate.year,
        cover_url=candidate.cover_url,
        source=candidate.source.value,
        external_id=candidate.external_id,
    )


async def decorate(
    session: AsyncSession, user_id: int, briefs: list[BookBrief]
) -> list[BookBrief]:
    """Дописывает в готовые строки состояние пользователя и счётчик спроса."""
    ids = [b.id for b in briefs if b.id is not None]
    entries = await my_entries(session, user_id, ids)
    demanded = await my_demands(session, user_id, ids)
    counts = await demand_counts(session, ids)

    for brief in briefs:
        if brief.id is None:
            continue
        entry = entries.get(brief.id)
        if entry is not None:
            brief.reading_status = entry.status
            brief.my_score = entry.score
            brief.liked = entry.liked
            brief.favourite_position = entry.favourite_position
        brief.demanded = brief.id in demanded
        brief.demand_count = counts.get(brief.id, (0, 0))[0]
    return briefs


async def card(session: AsyncSession, user_id: int, book: Book) -> BookCard:
    entry = (
        await session.execute(
            sa.select(ReadingEntry).where(
                ReadingEntry.user_id == user_id, ReadingEntry.book_id == book.id
            )
        )
    ).scalar_one_or_none()

    stats = (
        await session.execute(
            sa.select(
                sa.func.avg(ReadingEntry.score),
                sa.func.count(ReadingEntry.score),
                sa.func.count().filter(ReadingEntry.status == ReadingStatus.FINISHED),
            ).where(ReadingEntry.book_id == book.id)
        )
    ).one()
    avg_score, ratings_count, readers_count = stats

    waiting, readers = (await demand_counts(session, [book.id])).get(book.id, (0, 0))

    type_rows = await session.execute(
        sa.select(EventType.id, EventType.title, sa.func.count())
        .join(DemandType, DemandType.event_type_id == EventType.id)
        .join(Demand, Demand.id == DemandType.demand_id)
        .where(Demand.book_id == book.id, Demand.revoked_at.is_(None))
        .group_by(EventType.id, EventType.title)
        .order_by(sa.func.count().desc())
    )

    my_types = (
        await session.execute(
            sa.select(DemandType.event_type_id)
            .join(Demand, Demand.id == DemandType.demand_id)
            .where(
                Demand.book_id == book.id,
                Demand.user_id == user_id,
                Demand.revoked_at.is_(None),
            )
        )
    ).scalars()

    open_event = (
        await session.execute(
            sa.select(Event.id)
            .where(
                Event.book_id == book.id,
                Event.status.in_(
                    (EventStatus.SLOT_SELECTION, EventStatus.VOTING, EventStatus.SCHEDULED)
                ),
            )
            .order_by(Event.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    my_application = (
        await session.execute(
            sa.select(OrganizerApplication.status)
            .where(
                OrganizerApplication.book_id == book.id,
                OrganizerApplication.user_id == user_id,
                OrganizerApplication.status.in_(
                    (ApplicationStatus.SUBMITTED, ApplicationStatus.CHAT_OPEN)
                ),
            )
            .limit(1)
        )
    ).scalar_one_or_none()

    return BookCard(
        # Состояние пользователя задаётся ниже явно, поэтому из краткой формы
        # берём только сведения о самой книге.
        **brief_from_book(book).model_dump(
            exclude={
                "reading_status",
                "my_score",
                "liked",
                "favourite_position",
                "demanded",
                "demand_count",
            }
        ),
        description=book.description,
        page_count=book.page_count,
        isbn13=book.isbn13,
        genres=list(book.genres or []),
        language=book.language,
        avg_score=round(float(avg_score), 2) if avg_score is not None else None,
        ratings_count=ratings_count or 0,
        readers_count=readers_count or 0,
        demand_readers=readers,
        demand_types=[
            DemandTypeCount(event_type_id=type_id, title=title, count=count)
            for type_id, title, count in type_rows
        ],
        my_demand_type_ids=list(my_types),
        reading_status=entry.status if entry else None,
        my_score=entry.score if entry else None,
        liked=entry.liked if entry else False,
        favourite_position=entry.favourite_position if entry else None,
        my_review=entry.review if entry else None,
        my_started_on=entry.started_on if entry else None,
        my_finished_on=entry.finished_on if entry else None,
        demanded=bool(await my_demands(session, user_id, [book.id])),
        demand_count=waiting,
        open_event_id=open_event,
        my_application_status=my_application,
    )
