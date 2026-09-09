"""Сессии и права доступа."""

from datetime import UTC, datetime, timedelta
from typing import Annotated

import jwt
import sqlalchemy as sa
from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_config
from app.db import get_session
from app.models import Profile, User
from app.models.enums import UserRole

ALGORITHM = "HS256"

NEED_ONBOARDING = "Сначала заполните анкету"


def issue_token(user_id: int) -> str:
    config = get_config()
    payload = {
        "sub": str(user_id),
        "exp": datetime.now(UTC) + timedelta(hours=config.session_ttl_hours),
        "iat": datetime.now(UTC),
    }
    return jwt.encode(payload, config.secret_key, algorithm=ALGORITHM)


async def authenticated_user(
    session: Annotated[AsyncSession, Depends(get_session)],
    authorization: Annotated[str | None, Header()] = None,
) -> User:
    """Вошедший, но, возможно, ещё без анкеты.

    Ею пользуются ровно те ручки, которые обязаны работать до анкеты, — иначе
    заполнить её было бы негде.
    """
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Требуется авторизация")
    token = authorization.split(" ", 1)[1]
    try:
        payload = jwt.decode(token, get_config().secret_key, algorithms=[ALGORITHM])
    except jwt.PyJWTError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Недействительная сессия") from exc

    user = await session.get(User, int(payload["sub"]))
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Аккаунт недоступен")

    await session.execute(
        sa.update(User).where(User.id == user.id).values(last_seen_at=sa.func.now())
    )
    await session.commit()
    return user


AuthenticatedUser = Annotated[User, Depends(authenticated_user)]


async def current_user(
    user: AuthenticatedUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> User:
    """Обычная зависимость: вход плюс пройденная анкета.

    Проверка стоит в единственной точке, через которую проходят все ручки:
    гейт, который где-то забыли повесить, — не гейт.
    """
    profile = await session.get(Profile, user.id)
    if profile is None or profile.completed_at is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, NEED_ONBOARDING)
    return user


CurrentUser = Annotated[User, Depends(current_user)]


def require_role(minimum: UserRole):
    async def dependency(user: CurrentUser) -> User:
        if user.role.rank < minimum.rank:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Недостаточно прав")
        return user

    return dependency


RequireModerator = Annotated[User, Depends(require_role(UserRole.MODERATOR))]
RequireAdmin = Annotated[User, Depends(require_role(UserRole.ADMIN))]
RequireSuperadmin = Annotated[User, Depends(require_role(UserRole.SUPERADMIN))]
