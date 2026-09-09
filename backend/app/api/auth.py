import logging
from typing import Annotated

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_config
from app.core.auth import AuthenticatedUser, issue_token
from app.core.telegram_auth import BotNotConfigured, InitDataError, parse_init_data
from app.db import get_session
from app.models import Profile, User
from app.models.enums import UserRole
from app.schemas import AuthOut, TelegramAuthIn, UserOut

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/telegram", response_model=AuthOut)
async def login_via_telegram(
    body: TelegramAuthIn, session: Annotated[AsyncSession, Depends(get_session)]
) -> AuthOut:
    config = get_config()
    try:
        tg_user = parse_init_data(body.init_data, config.telegram_bot_token)
    except BotNotConfigured as exc:
        # Причину пишем в лог, наружу отдаём нейтральное: имена переменных
        # окружения — не дело пользователя.
        logger.error("Вход невозможен: %s", exc)
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Сервис временно недоступен, попробуйте позже.",
        ) from exc
    except InitDataError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(exc)) from exc

    user = (
        await session.execute(sa.select(User).where(User.tg_id == tg_user.tg_id))
    ).scalar_one_or_none()

    if user is None:
        user = User(
            tg_id=tg_user.tg_id,
            tg_username=tg_user.username,
            display_name=tg_user.display_name,
            photo_url=tg_user.photo_url,
            tz=config.display_timezone,
            # Первый суперадмин назначается из окружения: иначе некому выдать
            # роли остальным.
            role=(
                UserRole.SUPERADMIN
                if config.bootstrap_superadmin_tg_id == tg_user.tg_id
                else UserRole.USER
            ),
        )
        session.add(user)
    else:
        user.tg_username = tg_user.username
        user.display_name = tg_user.display_name
        user.photo_url = tg_user.photo_url

    await session.commit()
    await session.refresh(user)
    return AuthOut(token=issue_token(user.id), user=await user_out(session, user))


async def user_out(session: AsyncSession, user: User) -> UserOut:
    """Признак анкеты считается здесь: приложению надо решить, показывать
    онбординг или сам клуб."""
    profile = await session.get(Profile, user.id)
    return UserOut(
        id=user.id,
        display_name=user.display_name,
        role=user.role,
        photo_url=user.photo_url,
        tg_username=user.tg_username,
        onboarded=profile is not None and profile.completed_at is not None,
    )


@router.get("/me", response_model=UserOut)
async def me(
    user: AuthenticatedUser, session: Annotated[AsyncSession, Depends(get_session)]
) -> UserOut:
    return await user_out(session, user)
