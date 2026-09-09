"""Доставка уведомлений в Telegram.

Уведомления пишутся в таблицу теми, кто их порождает, а отправляются отдельной
задачей бота. Так у отправки одно место, где живут повторные попытки, а запись
переживает падение процесса: неотправленное уйдёт следующим проходом.

Идемпотентность держится на dedup_key: повторный запуск фоновой задачи не
создаёт вторую запись, а значит и второго сообщения.

Всё, что нужно для текста, кладётся в payload в момент постановки в очередь.
Отправка не ходит за контекстом в базу: сообщение должно описывать событие
таким, каким оно было, а не таким, каким запись стала спустя сутки.
"""

import logging

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Notification
from app.models.enums import NotificationKind

logger = logging.getLogger(__name__)

# Сколько сообщений отправляем за один проход. Telegram допускает ~30 сообщений
# в секунду; проход раз в несколько секунд с таким размером в лимит укладывается.
BATCH = 25


async def queue(
    session: AsyncSession,
    user_id: int,
    kind: NotificationKind,
    dedup_key: str | None = None,
    payload: dict | None = None,
) -> bool:
    """Ставит уведомление в очередь, пропуская уже поставленное.

    dedup_key уникален, поэтому обычный session.add() на повторе ронял бы
    IntegrityError и вместе с ним весь пакет — а повтор здесь ожидаем: фоновые
    задачи выполняются много раз и обязаны быть идемпотентными.
    """
    stmt = (
        insert(Notification)
        .values(user_id=user_id, kind=kind, dedup_key=dedup_key, payload=payload or {})
        .on_conflict_do_nothing(index_elements=[Notification.dedup_key])
        .returning(Notification.id)
    )
    return (await session.execute(stmt)).scalar_one_or_none() is not None


async def queue_many(
    session: AsyncSession,
    user_ids: list[int],
    kind: NotificationKind,
    dedup_prefix: str | None = None,
    payload: dict | None = None,
) -> int:
    """То же для группы. dedup_key собирается как «префикс:id получателя»."""
    sent = 0
    for user_id in dict.fromkeys(user_ids):  # без дублей, порядок сохраняется
        key = f"{dedup_prefix}:{user_id}" if dedup_prefix else None
        sent += await queue(session, user_id, kind, key, payload)
    return sent


def _book(payload: dict) -> str:
    title = payload.get("book_title") or "книга"
    authors = payload.get("book_authors")
    return f"<b>{title}</b>" + (f" — {authors}" if authors else "")


def render(kind: NotificationKind, payload: dict) -> str | None:
    """Текст сообщения. None — значит для этого вида текста пока нет."""
    book = _book(payload)
    when = payload.get("when", "")
    event_type = payload.get("event_type", "встреча")

    match kind:
        case NotificationKind.DEMAND_THRESHOLD:
            waiting = payload.get("waiting", 0)
            return (
                f"📚 Спрос набрался\n\n{book}\nЖдут встречу: {waiting}\n\n"
                "Пора искать ведущего — или объявить, что ведёте вы."
            )
        case NotificationKind.APPLICATION_SUBMITTED:
            return (
                f"🙋 Заявка на организацию\n\n{book}\nФормат: {event_type}\n"
                f"От кого: {payload.get('user_name', 'участник')}\n\n"
                "Откройте переговорку в приложении, чтобы обсудить детали."
            )
        case NotificationKind.APPLICATION_CHAT_OPEN:
            link = payload.get("invite_link")
            tail = f"\n\n{link}" if link else ""
            return (
                f"💬 Оргкомитет готов обсудить вашу встречу\n\n{book}\n\n"
                f"Заходите в чат по ссылке — она одноразовая и скоро истечёт.{tail}"
            )
        case NotificationKind.APPLICATION_APPROVED:
            return (
                f"✅ Заявку одобрили\n\n{book}\nФормат: {event_type}\n\n"
                "Осталось предложить время: откройте приложение и расставьте "
                "удобные вам окна."
            )
        case NotificationKind.APPLICATION_REJECTED:
            comment = payload.get("comment")
            tail = f"\n\nКомментарий: {comment}" if comment else ""
            return f"❌ Заявку отклонили\n\n{book}{tail}"
        case NotificationKind.NO_FREE_ROOM:
            return (
                "⚠️ Нет свободных переговорок\n\n"
                f"{book}: заявка ждёт чата. Освободите комнату или добавьте новую."
            )
        case NotificationKind.SLOT_VOTING_OPEN:
            return (
                f"🗳 Выбираем время\n\n{book}\nФормат: {event_type}\n\n"
                "Отметьте в приложении все окна, которые вам подходят. "
                f"Голосование до {payload.get('deadline', 'дедлайна')}."
            )
        case NotificationKind.EVENT_SCHEDULED:
            place = payload.get("place")
            tail = f"\nМесто: {place}" if place else ""
            return f"📅 Время назначено\n\n{book}\n{when}{tail}\n\nОтметьтесь, придёте ли."
        case NotificationKind.EVENT_CHANGED:
            return (
                f"🔄 Встреча изменилась\n\n{book}\nНовое время: {when}\n\n"
                "Подтверждения сброшены — отметьтесь заново, если придёте."
            )
        case NotificationKind.EVENT_CANCELLED:
            reason = payload.get("reason", "без указания причины")
            return f"❌ Встреча отменена\n\n{book}\n{when}\n\nПричина: {reason}"
        case NotificationKind.REMINDER_24H:
            return (
                f"⏰ Завтра встреча\n\n{book}\n{when}\n\n"
                "Если планы изменились — отмените заранее."
            )
        case NotificationKind.REMINDER_2H:
            return f"⏰ Через два часа\n\n{book}\n{when}\n\nДо встречи!"
        case NotificationKind.LOW_ATTENDANCE:
            return (
                f"⚠️ Мало подтверждений\n\n{book}\n{when}\n\n"
                f"Придут {payload.get('going', 0)}, кворум {payload.get('quorum', 0)}. "
                "Решение о проведении за вами."
            )
        case NotificationKind.FEEDBACK_REQUEST:
            return f"⭐️ Как прошло?\n\n{book}\n\nОцените встречу — это займёт полминуты."
        case NotificationKind.FRIEND_REQUEST:
            return f"👋 {payload.get('user_name', 'Участник')} хочет добавить вас в друзья."
        case NotificationKind.FRIEND_ACCEPTED:
            return f"🤝 {payload.get('user_name', 'Участник')} принял вашу заявку в друзья."
        case NotificationKind.ROLE_GRANTED:
            return f"🔑 Вам выдали роль: {payload.get('role_title', 'новая роль')}."
        case NotificationKind.BOOK_REQUEST_DECIDED:
            if payload.get("approved"):
                return f"📗 Книгу добавили в каталог\n\n{book}"
            comment = payload.get("comment")
            tail = f"\n\nКомментарий: {comment}" if comment else ""
            return f"📕 Книгу не добавили\n\n{book}{tail}"
    return None


async def pending(session: AsyncSession, limit: int = BATCH) -> list[Notification]:
    return list(
        (
            await session.execute(
                sa.select(Notification)
                .where(Notification.sent_at.is_(None), Notification.failed_reason.is_(None))
                .order_by(Notification.id)
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
