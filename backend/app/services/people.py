"""Как называть человека.

В Telegram у людей стоит что угодно — ник, эмодзи, одно имя. В анкете они
пишут фамилию и имя, и именно это должен видеть клуб: в списке идущих,
в заявке, в карточке встречи. Ник остаётся способом связи, а не подписью.
"""

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Profile, User


async def names(session: AsyncSession, user_ids: list[int]) -> dict[int, str]:
    """{id: «Фамилия Имя»}. Для тех, кто ещё не прошёл анкету, — имя из Telegram."""
    if not user_ids:
        return {}
    rows = await session.execute(
        sa.select(User.id, Profile.full_name, User.display_name)
        .outerjoin(Profile, Profile.user_id == User.id)
        .where(User.id.in_(set(user_ids)))
    )
    return {user_id: (full_name or display_name) for user_id, full_name, display_name in rows}


async def name_of(session: AsyncSession, user_id: int | None) -> str:
    if user_id is None:
        return ""
    return (await names(session, [user_id])).get(user_id, "")
