"""Друзья: поиск участников, заявки, принятие."""

from datetime import UTC, datetime
from typing import Annotated

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import CurrentUser
from app.db import get_session
from app.models import Friendship, Profile, User
from app.models.enums import FriendshipStatus, NotificationKind
from app.schemas import FriendsOut, PersonBrief, PersonProfileOut
from app.services import cards, notify, profiles

router = APIRouter(prefix="/api/friends", tags=["friends"])


async def _relation(session: AsyncSession, me: int, other: int) -> str:
    row = (
        await session.execute(
            sa.select(Friendship).where(
                sa.or_(
                    sa.and_(Friendship.from_user_id == me, Friendship.to_user_id == other),
                    sa.and_(Friendship.from_user_id == other, Friendship.to_user_id == me),
                )
            )
        )
    ).scalar_one_or_none()
    if row is None:
        return "none"
    if row.status is FriendshipStatus.ACCEPTED:
        return "friends"
    if row.status is FriendshipStatus.PENDING:
        return "outgoing" if row.from_user_id == me else "incoming"
    return "none"


async def _brief(session: AsyncSession, person: User, me: int) -> PersonBrief:
    profile = await session.get(Profile, person.id)
    return PersonBrief(
        id=person.id,
        # Фамилия и имя из анкеты: ник в Telegram у людей стоит какой угодно,
        # а в клубе друг друга знают по имени.
        display_name=(profile.full_name if profile else None) or person.display_name,
        photo_url=person.photo_url,
        tg_username=person.tg_username,
        member_kind=profile.member_kind if profile else None,
        member_kind_title=(
            profiles.KIND_TITLES.get(profile.member_kind) if profile else None
        ),
        friendship=await _relation(session, me, person.id),
    )


@router.get("/{user_id}/profile", response_model=PersonProfileOut)
async def person_profile(
    user_id: int,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> PersonProfileOut:
    """Чужой профиль: витрина любимых книг и немного цифр.

    Открыт всем участникам клуба, а не только друзьям: люди приходят сюда
    именно знакомиться, и закрытый профиль этому мешает.
    """
    person = await session.get(User, user_id)
    profile = await session.get(Profile, user_id)
    if person is None or profile is None or profile.completed_at is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Участник не найден")

    from app.models import Attendance, ReadingEntry
    from app.models.enums import ReadingStatus

    finished = (
        await session.execute(
            sa.select(sa.func.count()).where(
                ReadingEntry.user_id == user_id,
                ReadingEntry.status == ReadingStatus.FINISHED,
            )
        )
    ).scalar_one()
    attended = (
        await session.execute(
            sa.select(sa.func.count()).where(Attendance.user_id == user_id)
        )
    ).scalar_one()

    return PersonProfileOut(
        person=await _brief(session, person, user.id),
        about=profile.about,
        favourites=await cards.favourites(session, user_id),
        finished=finished,
        events_attended=attended,
        genres=list(profile.genres or []),
    )


@router.get("", response_model=FriendsOut)
async def listing(
    user: CurrentUser, session: Annotated[AsyncSession, Depends(get_session)]
) -> FriendsOut:
    rows = (
        await session.execute(
            sa.select(Friendship).where(
                sa.or_(Friendship.from_user_id == user.id, Friendship.to_user_id == user.id)
            )
        )
    ).scalars()

    friends: list[PersonBrief] = []
    incoming: list[PersonBrief] = []
    outgoing: list[PersonBrief] = []
    for row in rows:
        other_id = row.to_user_id if row.from_user_id == user.id else row.from_user_id
        other = await session.get(User, other_id)
        if other is None:
            continue
        brief = await _brief(session, other, user.id)
        if row.status is FriendshipStatus.ACCEPTED:
            friends.append(brief)
        elif row.status is FriendshipStatus.PENDING:
            (outgoing if row.from_user_id == user.id else incoming).append(brief)
    return FriendsOut(friends=friends, incoming=incoming, outgoing=outgoing)


@router.get("/search", response_model=list[PersonBrief])
async def search(
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    q: str = Query(min_length=2, max_length=100),
) -> list[PersonBrief]:
    """Поиск среди тех, кто прошёл анкету: незаполненный профиль в клубе
    ещё не участник, и находить его незачем."""
    pattern = f"%{q.strip()}%"
    rows = (
        await session.execute(
            sa.select(User)
            .join(Profile, Profile.user_id == User.id)
            .where(
                User.id != user.id,
                User.is_active,
                Profile.completed_at.is_not(None),
                sa.or_(
                    User.display_name.ilike(pattern),
                    User.tg_username.ilike(pattern),
                    Profile.full_name.ilike(pattern),
                ),
            )
            .order_by(User.display_name)
            .limit(20)
        )
    ).scalars()
    return [await _brief(session, person, user.id) for person in rows]


@router.post("/{user_id}", response_model=PersonBrief)
async def request_friendship(
    user_id: int,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> PersonBrief:
    """Заявка в друзья. Встречная заявка не плодит вторую строку, а принимает
    первую — иначе двое, нажавшие одновременно, зависли бы навсегда."""
    if user_id == user.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Себя добавить нельзя")
    other = await session.get(User, user_id)
    if other is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Участник не найден")

    existing = (
        await session.execute(
            sa.select(Friendship).where(
                sa.or_(
                    sa.and_(
                        Friendship.from_user_id == user.id, Friendship.to_user_id == user_id
                    ),
                    sa.and_(
                        Friendship.from_user_id == user_id, Friendship.to_user_id == user.id
                    ),
                )
            )
        )
    ).scalar_one_or_none()

    if existing is None:
        session.add(Friendship(from_user_id=user.id, to_user_id=user_id))
        await notify.queue(
            session,
            user_id,
            NotificationKind.FRIEND_REQUEST,
            f"friendreq:{user.id}:{user_id}",
            {"user_name": user.display_name},
        )
    elif existing.status is FriendshipStatus.PENDING and existing.to_user_id == user.id:
        existing.status = FriendshipStatus.ACCEPTED
        existing.decided_at = datetime.now(UTC)
        await notify.queue(
            session,
            existing.from_user_id,
            NotificationKind.FRIEND_ACCEPTED,
            f"friendok:{existing.id}",
            {"user_name": user.display_name},
        )
    elif existing.status is FriendshipStatus.DECLINED:
        existing.status = FriendshipStatus.PENDING
        existing.from_user_id, existing.to_user_id = user.id, user_id
        existing.decided_at = None

    await session.commit()
    return await _brief(session, other, user.id)


@router.delete("/{user_id}", status_code=204)
async def drop(
    user_id: int,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> None:
    """Отклонить заявку или удалить из друзей — одна и та же кнопка «убрать»."""
    await session.execute(
        sa.delete(Friendship).where(
            sa.or_(
                sa.and_(Friendship.from_user_id == user.id, Friendship.to_user_id == user_id),
                sa.and_(Friendship.from_user_id == user_id, Friendship.to_user_id == user.id),
            )
        )
    )
    await session.commit()
