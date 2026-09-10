"""Личные списки: мои книги и мои встречи.

Вкладки «Дневник» нет — всё про книгу живёт на её карточке. Но список
прочитанного нужен, и он открывается из профиля.
"""

from typing import Annotated

import sqlalchemy as sa
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import CurrentUser
from app.db import get_session
from app.models import Attendance, Book, Event, Friendship, Participation, ReadingEntry
from app.models.enums import FriendshipStatus, ReadingStatus
from app.schemas import BookBrief, EventOut
from app.services import cards, eventcards

router = APIRouter(prefix="/api/me", tags=["me"])


@router.get("/books", response_model=list[BookBrief])
async def my_books(
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    status: ReadingStatus | None = Query(default=None),
) -> list[BookBrief]:
    stmt = (
        sa.select(Book)
        .join(ReadingEntry, ReadingEntry.book_id == Book.id)
        .where(ReadingEntry.user_id == user.id)
        .order_by(ReadingEntry.updated_at.desc())
    )
    if status is not None:
        stmt = stmt.where(ReadingEntry.status == status)
    books = list((await session.execute(stmt)).scalars().all())
    return await cards.decorate(session, user.id, [cards.brief_from_book(b) for b in books])


@router.get("/stats")
async def my_stats(
    user: CurrentUser, session: Annotated[AsyncSession, Depends(get_session)]
) -> dict:
    """Цифры для профиля.

    Средняя оценка отдаётся вместе с распределением: одно число говорит
    мало — по нему не отличить того, кто всем ставит четвёрки, от того,
    у кого половина книг любимые, а половина брошены.
    """
    total, avg_score = (
        await session.execute(
            sa.select(
                sa.func.count().filter(ReadingEntry.status == ReadingStatus.FINISHED),
                sa.func.avg(ReadingEntry.score),
            ).where(ReadingEntry.user_id == user.id)
        )
    ).one()

    attended = (
        await session.execute(
            sa.select(sa.func.count()).where(Attendance.user_id == user.id)
        )
    ).scalar_one()

    friends = (
        await session.execute(
            sa.select(sa.func.count()).where(
                Friendship.status == FriendshipStatus.ACCEPTED,
                sa.or_(
                    Friendship.from_user_id == user.id, Friendship.to_user_id == user.id
                ),
            )
        )
    ).scalar_one()

    # Оценки в полубаллах 1..10 — десять корзин, по одной на половину звезды.
    counts = dict(
        (
            await session.execute(
                sa.select(ReadingEntry.score, sa.func.count())
                .where(ReadingEntry.user_id == user.id, ReadingEntry.score.is_not(None))
                .group_by(ReadingEntry.score)
            )
        ).all()
    )

    return {
        "finished": total or 0,
        "avg_score": round(float(avg_score), 2) if avg_score is not None else None,
        "events_attended": attended or 0,
        "friends": friends or 0,
        "ratings": sum(counts.values()),
        "ratings_by_score": [counts.get(score, 0) for score in range(1, 11)],
    }


@router.get("/events", response_model=list[EventOut])
async def my_events(
    user: CurrentUser, session: Annotated[AsyncSession, Depends(get_session)]
) -> list[EventOut]:
    """Встречи, где я организатор или записан."""
    stmt = (
        sa.select(Event)
        .outerjoin(
            Participation,
            sa.and_(Participation.event_id == Event.id, Participation.user_id == user.id),
        )
        .where(
            sa.or_(Event.organizer_user_id == user.id, Participation.id.is_not(None))
        )
        .order_by(Event.id.desc())
    )
    events = list((await session.execute(stmt)).scalars().unique().all())
    return [await eventcards.event_out(session, event, user) for event in events]
