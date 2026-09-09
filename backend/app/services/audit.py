"""Журнал решений.

Пишем всё, что меняет чужое состояние: одобрение заявки, закрепление времени,
выдачу роли. Ценность записи в том, что она отвечает на вопрос «кто и почему»,
поэтому comment здесь не украшение.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditLog


def log(
    session: AsyncSession,
    *,
    actor_id: int | None,
    entity: str,
    entity_id: int | None,
    action: str,
    payload: dict | None = None,
    comment: str | None = None,
) -> None:
    """Кладёт запись в сессию. Коммитит вызывающий — вместе со своим изменением,
    чтобы журнал не разошёлся с тем, что произошло на самом деле."""
    session.add(
        AuditLog(
            actor_id=actor_id,
            entity=entity,
            entity_id=entity_id,
            action=action,
            payload=payload or {},
            comment=comment,
        )
    )
