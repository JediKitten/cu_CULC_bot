"""Спрос на встречи: отметки «хочу обсудить эту книгу».

Активная отметка одна на пару «человек — книга», форматов у неё может быть
несколько. Снятая отметка не удаляется — по ней считается аналитика спроса,
который так и не дошёл до встречи.
"""

from datetime import UTC, datetime

import sqlalchemy as sa
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Demand, DemandType, EventType, ReadingEntry, User
from app.models.enums import (
    EventTypeStatus,
    NotificationKind,
    ReadingStatus,
    RevokeReason,
    UserRole,
)
from app.services import notify
from app.services.settings import SettingsService


async def active(session: AsyncSession, user_id: int, book_id: int) -> Demand | None:
    return (
        await session.execute(
            sa.select(Demand).where(
                Demand.user_id == user_id,
                Demand.book_id == book_id,
                Demand.revoked_at.is_(None),
            )
        )
    ).scalar_one_or_none()


async def set_demand(
    session: AsyncSession,
    user: User,
    book_id: int,
    event_type_ids: list[int],
    comment: str | None = None,
) -> Demand:
    """Ставит или обновляет отметку.

    Читать книгу заранее не требуем: на круглый стол и мастер-класс ходят и
    не читая, а требование «сначала прочти» просто выключило бы половину клуба
    из спроса. Но факт чтения фиксируем — оргкомитету важно видеть, сколько из
    ожидающих книгу действительно знают.
    """
    allowed = set(
        (
            await session.execute(
                sa.select(EventType.id).where(
                    EventType.id.in_(event_type_ids),
                    EventType.status == EventTypeStatus.ACTIVE,
                )
            )
        )
        .scalars()
        .all()
    )
    if not allowed:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Выберите хотя бы один формат встречи")

    entry = (
        await session.execute(
            sa.select(ReadingEntry).where(
                ReadingEntry.user_id == user.id, ReadingEntry.book_id == book_id
            )
        )
    ).scalar_one_or_none()
    has_read = entry is not None and entry.status is ReadingStatus.FINISHED

    demand = await active(session, user.id, book_id)
    if demand is None:
        demand = Demand(user_id=user.id, book_id=book_id)
        session.add(demand)
    demand.has_read = has_read
    demand.comment = (comment or "").strip() or None
    await session.flush()

    await session.execute(sa.delete(DemandType).where(DemandType.demand_id == demand.id))
    for event_type_id in sorted(allowed):
        session.add(DemandType(demand_id=demand.id, event_type_id=event_type_id))

    await session.flush()
    await maybe_alert(session, book_id)
    await session.commit()
    await session.refresh(demand)
    return demand


async def revoke(
    session: AsyncSession,
    user_id: int,
    book_id: int,
    reason: RevokeReason = RevokeReason.MANUAL,
) -> None:
    demand = await active(session, user_id, book_id)
    if demand is None:
        return
    demand.revoked_at = datetime.now(UTC)
    demand.revoke_reason = reason
    await session.commit()


async def count(session: AsyncSession, book_id: int) -> int:
    return (
        await session.execute(
            sa.select(sa.func.count()).where(
                Demand.book_id == book_id, Demand.revoked_at.is_(None)
            )
        )
    ).scalar_one()


async def maybe_alert(session: AsyncSession, book_id: int) -> None:
    """Дёргает оргкомитет, когда спрос перевалил порог.

    dedup_key завязан на книгу и порог, а не на время: перешагнули четвёрку —
    сообщили один раз, а не на каждой новой отметке.
    """
    settings = SettingsService(session)
    threshold = await settings.get("demand_threshold")
    waiting = await count(session, book_id)
    if waiting < threshold:
        return

    from app.models import Book  # локальный импорт: иначе цикл через cards

    book = await session.get(Book, book_id)
    admins = (
        (
            await session.execute(
                sa.select(User.id).where(
                    User.role.in_((UserRole.ADMIN, UserRole.SUPERADMIN)), User.is_active
                )
            )
        )
        .scalars()
        .all()
    )
    await notify.queue_many(
        session,
        list(admins),
        NotificationKind.DEMAND_THRESHOLD,
        dedup_prefix=f"demand:{book_id}:{threshold}",
        payload={
            "book_id": book_id,
            "book_title": book.title if book else "",
            "book_authors": ", ".join((book.authors or [])[:2]) if book else "",
            "waiting": waiting,
        },
    )
