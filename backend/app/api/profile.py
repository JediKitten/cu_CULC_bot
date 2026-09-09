from typing import Annotated

import sqlalchemy as sa
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthenticatedUser
from app.db import get_session
from app.models import Profile, ProfileEventType
from app.models.demand import EventType
from app.models.enums import EventTypeStatus
from app.schemas import EventTypeOut, ProfileIn, ProfileOut, ReferenceOut
from app.services import profiles
from app.services.reference import GENRES

router = APIRouter(prefix="/api/profile", tags=["profile"])


@router.get("/reference", response_model=ReferenceOut)
async def reference(
    _: AuthenticatedUser, session: Annotated[AsyncSession, Depends(get_session)]
) -> ReferenceOut:
    """Справочники для анкеты. Доступно до её заполнения — иначе нечем
    нарисовать сам онбординг."""
    rows = (
        await session.execute(
            sa.select(EventType)
            .where(EventType.status == EventTypeStatus.ACTIVE)
            .order_by(EventType.sort_order, EventType.id)
        )
    ).scalars()
    return ReferenceOut(
        genres=list(GENRES),
        event_types=[EventTypeOut.model_validate(row, from_attributes=True) for row in rows],
    )


@router.get("", response_model=ProfileOut | None)
async def get_profile(
    user: AuthenticatedUser, session: Annotated[AsyncSession, Depends(get_session)]
) -> ProfileOut | None:
    profile = await session.get(Profile, user.id)
    return None if profile is None else await _out(session, profile)


@router.put("", response_model=ProfileOut)
async def save_profile(
    body: ProfileIn,
    user: AuthenticatedUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ProfileOut:
    profile = await profiles.save(
        session,
        user.id,
        member_kind=body.member_kind,
        full_name=body.full_name,
        faculty=body.faculty,
        year=body.year,
        university_email=body.university_email,
        reading_pace=body.reading_pace,
        club_experience=body.club_experience,
        genres=body.genres,
        event_type_ids=body.event_type_ids,
        about=body.about,
    )
    return await _out(session, profile)


async def _out(session: AsyncSession, profile: Profile) -> ProfileOut:
    ids = (
        (
            await session.execute(
                sa.select(ProfileEventType.event_type_id).where(
                    ProfileEventType.profile_id == profile.user_id
                )
            )
        )
        .scalars()
        .all()
    )
    return ProfileOut(
        member_kind=profile.member_kind,
        full_name=profile.full_name,
        faculty=profile.faculty,
        year=profile.year,
        university_email=profile.university_email,
        reading_pace=profile.reading_pace,
        club_experience=profile.club_experience,
        genres=list(profile.genres or []),
        event_type_ids=list(ids),
        about=profile.about,
        completed_at=profile.completed_at,
        email_required=profiles.email_required(profile.member_kind),
    )
