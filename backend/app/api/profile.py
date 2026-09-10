from typing import Annotated

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthenticatedUser
from app.db import get_session
from app.models import Profile, ProfileEventType
from app.models.demand import EventType
from app.models.enums import EventTypeStatus, MemberKind
from app.schemas import (
    DismissIn,
    EventTypeOut,
    IdentityIn,
    KindOut,
    PreferencesIn,
    ProfileOut,
    ReferenceOut,
)
from app.services import cards, profiles
from app.services.reference import GENRES

router = APIRouter(prefix="/api/profile", tags=["profile"])


@router.get("/reference", response_model=ReferenceOut)
async def reference(
    _: AuthenticatedUser, session: Annotated[AsyncSession, Depends(get_session)]
) -> ReferenceOut:
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
        kinds=[
            KindOut(key=kind, title=title, email_required=profiles.email_required(kind))
            for kind, title in profiles.KIND_TITLES.items()
        ],
        email_domains=list(profiles.CU_EMAIL_DOMAINS),
    )


@router.get("", response_model=ProfileOut | None)
async def get_profile(
    user: AuthenticatedUser, session: Annotated[AsyncSession, Depends(get_session)]
) -> ProfileOut | None:
    profile = await session.get(Profile, user.id)
    return None if profile is None else await out(session, profile)


@router.put("/identity", response_model=ProfileOut)
async def save_identity(
    body: IdentityIn,
    user: AuthenticatedUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ProfileOut:
    """Правка обязательной части. Впервые её заполняют в боте — здесь только
    исправляют, если сменилась роль или в фамилии опечатка."""
    profile = await session.get(Profile, user.id)
    if profile is None or profile.completed_at is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Сначала пройдите регистрацию в боте")
    updated = await profiles.update_identity(
        session,
        user.id,
        full_name=body.full_name,
        member_kind=body.member_kind,
        university_email=body.university_email,
    )
    return await out(session, updated)


@router.put("/preferences", response_model=ProfileOut)
async def save_preferences(
    body: PreferencesIn,
    user: AuthenticatedUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ProfileOut:
    """Необязательная часть: вкусы. Пустые поля — это пропущенные вопросы,
    и они сохраняются как есть."""
    profile = await profiles.save_preferences(
        session,
        user.id,
        reading_pace=body.reading_pace,
        club_experience=body.club_experience,
        genres=body.genres,
        event_type_ids=body.event_type_ids,
        about=body.about,
    )
    return await out(session, profile)


@router.post("/dismiss-reminder", status_code=204)
async def dismiss_reminder(
    body: DismissIn,
    user: AuthenticatedUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> None:
    await profiles.dismiss_reminder(session, user.id, forever=body.forever)


async def out(session: AsyncSession, profile: Profile) -> ProfileOut:
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
        member_kind_title=profiles.KIND_TITLES.get(profile.member_kind, ""),
        full_name=profile.full_name,
        university_email=profile.university_email,
        reading_pace=profile.reading_pace,
        club_experience=profile.club_experience,
        genres=list(profile.genres or []),
        event_type_ids=list(ids),
        about=profile.about,
        completed_at=profile.completed_at,
        preferences_at=profile.preferences_at,
        needs_preferences=profiles.needs_preferences(profile),
        email_required=profiles.email_required(profile.member_kind),
        favourites=await cards.favourites(session, profile.user_id),
    )


def kind_title(kind: MemberKind | None) -> str | None:
    return profiles.KIND_TITLES.get(kind) if kind else None
