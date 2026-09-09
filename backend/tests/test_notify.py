"""Очередь уведомлений: идемпотентность и тексты."""

import sqlalchemy as sa

from app.models import Notification, User
from app.models.enums import NotificationKind
from app.services import notify


async def make_user(session, tg_id: int) -> User:
    user = User(tg_id=tg_id, display_name=f"Участник {tg_id}")
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


async def test_dedup_key_blocks_the_second_copy(session):
    """Фоновые задачи выполняются много раз и не должны слать второе сообщение."""
    user = await make_user(session, 5001)

    first = await notify.queue(
        session, user.id, NotificationKind.REMINDER_24H, "reminder:1:24h", {"when": "завтра"}
    )
    second = await notify.queue(
        session, user.id, NotificationKind.REMINDER_24H, "reminder:1:24h", {"when": "завтра"}
    )
    await session.commit()

    assert first is True
    assert second is False
    count = (
        await session.execute(sa.select(sa.func.count()).select_from(Notification))
    ).scalar_one()
    assert count == 1


async def test_queue_many_skips_duplicates_in_the_list(session):
    users = [await make_user(session, 5100 + i) for i in range(3)]
    ids = [u.id for u in users] + [users[0].id]

    sent = await notify.queue_many(
        session, ids, NotificationKind.SLOT_VOTING_OPEN, "voting:7", {"book_title": "Дюна"}
    )
    await session.commit()

    assert sent == 3


async def test_pending_returns_only_unsent(session):
    user = await make_user(session, 5200)
    await notify.queue(session, user.id, NotificationKind.FEEDBACK_REQUEST, "fb:1")
    await notify.queue(session, user.id, NotificationKind.FEEDBACK_REQUEST, "fb:2")
    await session.commit()

    rows = await notify.pending(session)
    assert len(rows) == 2

    rows[0].sent_at = sa.func.now()
    await session.commit()
    assert len(await notify.pending(session)) == 1


def test_every_kind_has_a_text():
    """Уведомление без текста — молчаливая дыра: событие произошло, а человек
    о нём не узнал."""
    payload = {
        "book_title": "Дюна",
        "book_authors": "Фрэнк Герберт",
        "when": "1 октября, 18:00",
        "waiting": 5,
        "user_name": "Иван",
        "role_title": "администратор",
        "comment": "нет зала",
    }
    missing = [kind for kind in NotificationKind if notify.render(kind, payload) is None]
    assert missing == []
