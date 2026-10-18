"""Переговорки — темы в форуме оргкомитета.

Бот не создаёт чаты, но заводит темы в заранее подключённом форуме. Проверяем
именно эту механику: тема под заявку, она переживает одобрение и исчезает,
когда встреча закончилась или не состоялась. Telegram подменён: тесты не
должны ходить в сеть, а нам важно, что именно бот пытается там сделать.
"""

from datetime import UTC, datetime, timedelta

import pytest
import sqlalchemy as sa

from app.models import Book, Event, EventSlot, EventType, MeetingRoom, OrganizerApplication, User
from app.models.enums import ApplicationStatus, EventStatus, UserRole
from app.services import applications as service
from app.services import events as events_service
from app.services import jobs, rooms
from app.services.books.normalize import dedup_key

FORUM = -100_500


class FakeBot:
    """Записывает вызовы вместо похода в Telegram."""

    def __init__(self) -> None:
        self.calls: list[tuple] = []
        self.thread_id = 10
        # Кто уже состоит в форуме: им ссылка не нужна.
        self.members: set[int] = set()
        self.is_forum = True

    async def me(self):
        return type("Me", (), {"id": 1})()

    async def get_chat(self, chat_id):
        return type("Chat", (), {"is_forum": self.is_forum, "title": "Оргкомитет"})()

    async def get_chat_member(self, chat_id, user_id):
        if user_id == 1:
            rights = {right: True for right in rooms.REQUIRED_RIGHTS}
            return type("Member", (), {"status": "administrator", **rights})()
        status = "member" if user_id in self.members else "left"
        return type("Member", (), {"status": status})()

    async def create_forum_topic(self, chat_id, name):
        self.thread_id += 1
        self.calls.append(("topic", chat_id, name))
        return type("Topic", (), {"message_thread_id": self.thread_id})()

    async def delete_forum_topic(self, chat_id, message_thread_id):
        self.calls.append(("delete_topic", chat_id, message_thread_id))

    async def send_message(self, chat_id, text, **kwargs):
        self.calls.append(("message", chat_id, kwargs.get("message_thread_id"), text))

    async def create_chat_invite_link(self, chat_id, **kwargs):
        self.calls.append(("link", chat_id))
        return type("Link", (), {"invite_link": f"https://t.me/+fake{chat_id}"})()

    async def ban_chat_member(self, chat_id, user_id):
        self.calls.append(("ban", chat_id, user_id))

    async def unban_chat_member(self, chat_id, user_id, only_if_banned=False):
        self.calls.append(("unban", chat_id, user_id))

    def kinds(self) -> list[str]:
        return [call[0] for call in self.calls]


@pytest.fixture
def bot(monkeypatch) -> FakeBot:
    fake = FakeBot()
    monkeypatch.setattr("app.services.rooms.get_bot", lambda: fake)
    return fake


async def make_application(session, user: User, *, title: str = "Пикник на обочине"):
    book = Book(title=title, authors=["Стругацкие"], dedup_key=dedup_key(title, ["Стругацкие"]))
    session.add(book)
    await session.flush()
    application = OrganizerApplication(
        user_id=user.id, book_id=book.id, answers={"Вы читали эту книгу?": True}
    )
    session.add(application)
    await session.commit()
    await session.refresh(application)
    return application


async def setup_application(session, *, forum: bool = True) -> OrganizerApplication:
    user = User(tg_id=4242, display_name="Кандидат", tg_username="candidate")
    session.add(user)
    if forum:
        session.add(MeetingRoom(chat_id=FORUM, title="Оргкомитет"))
    await session.flush()
    return await make_application(session, user)


async def approve(session, application) -> Event:
    admin = User(tg_id=1_000_001, display_name="Админ", role=UserRole.ADMIN)
    session.add(admin)
    await session.flush()
    event_type_id = (
        await session.execute(sa.select(EventType.id).order_by(EventType.id).limit(1))
    ).scalar_one()
    return await service.approve(
        session, application, actor=admin, audience=[], event_type_id=event_type_id, comment=None
    )


async def test_open_room_creates_topic_and_invites(session, bot):
    application = await setup_application(session)

    await service.open_room(session, application, actor_id=None)

    assert application.status is ApplicationStatus.CHAT_OPEN
    assert application.topic_id == bot.thread_id
    assert application.invite_link.startswith("https://t.me/+fake")
    assert bot.kinds() == ["topic", "message", "link"]
    # Тема говорит, о чём она: книга и кандидат.
    assert "Пикник" in bot.calls[0][2] and "Кандидат" in bot.calls[0][2]
    # Карточка заявки — внутри темы, а не в общем чате.
    assert bot.calls[1][2] == application.topic_id


async def test_member_of_forum_gets_no_invite(session, bot):
    """Кто уже в форуме — ведёт другую встречу, — тому ссылка не нужна."""
    application = await setup_application(session)
    bot.members.add(4242)

    await service.open_room(session, application, actor_id=None)

    assert application.topic_id is not None
    assert application.invite_link is None
    assert "link" not in bot.kinds()


async def test_no_forum_leaves_application_waiting(session, bot):
    application = await setup_application(session, forum=False)

    with pytest.raises(Exception):  # noqa: B017 — важен сам отказ, не его тип
        await service.open_room(session, application, actor_id=None)
    await session.refresh(application)
    assert application.status is ApplicationStatus.SUBMITTED
    assert application.topic_id is None


async def test_open_room_twice_does_not_make_a_second_topic(session, bot):
    application = await setup_application(session)

    await service.open_room(session, application, actor_id=None)
    with pytest.raises(Exception):  # noqa: B017
        await service.open_room(session, application, actor_id=None)

    assert bot.kinds().count("topic") == 1


async def test_approval_keeps_the_topic(session, bot):
    """После одобрения ведущему с оргкомитетом ещё договариваться о встрече —
    тема обязана остаться."""
    application = await setup_application(session)
    await service.open_room(session, application, actor_id=None)

    await approve(session, application)

    await session.refresh(application)
    assert application.topic_id is not None
    assert "delete_topic" not in bot.kinds() and "ban" not in bot.kinds()
    # В тему уходит весточка об одобрении.
    assert bot.calls[-1][0] == "message" and bot.calls[-1][2] == application.topic_id


async def test_approved_application_can_get_a_topic_later(session, bot):
    """Форум могли подключить уже после одобрения."""
    application = await setup_application(session, forum=False)
    await approve(session, application)
    session.add(MeetingRoom(chat_id=FORUM, title="Оргкомитет"))
    await session.commit()

    await service.open_room(session, application, actor_id=None)

    assert application.status is ApplicationStatus.APPROVED
    assert application.topic_id is not None


async def test_reject_deletes_topic_and_kicks(session, bot):
    application = await setup_application(session)
    await service.open_room(session, application, actor_id=None)
    topic_id = application.topic_id
    admin = User(tg_id=1_000_002, display_name="Админ", role=UserRole.ADMIN)
    session.add(admin)
    await session.flush()

    await service.reject(session, application, actor=admin, comment="Не сейчас")

    assert ("delete_topic", FORUM, topic_id) in bot.calls
    # Забанить и сразу разбанить — иначе человек остаётся в бане навсегда.
    assert bot.kinds().count("ban") == 1 and bot.kinds().count("unban") == 1
    assert application.topic_id is None


async def test_candidate_with_another_topic_stays(session, bot):
    """Выселять ведущего, у которого в форуме идёт другая встреча, нельзя."""
    first = await setup_application(session)
    user = await session.get(User, first.user_id)
    second = await make_application(session, user, title="Улитка на склоне")
    await service.open_room(session, first, actor_id=None)
    await service.open_room(session, second, actor_id=None)

    await service.withdraw(session, first)

    assert "delete_topic" in bot.kinds()
    assert "ban" not in bot.kinds()


async def test_admin_candidate_is_not_kicked(session, bot):
    application = await setup_application(session)
    user = await session.get(User, application.user_id)
    user.role = UserRole.ADMIN
    await session.commit()
    await service.open_room(session, application, actor_id=None)

    await service.withdraw(session, application)

    assert "delete_topic" in bot.kinds() and "ban" not in bot.kinds()


async def test_cancel_deletes_topic(session, bot):
    application = await setup_application(session)
    await service.open_room(session, application, actor_id=None)
    event = await approve(session, application)
    admin = await session.get(User, application.reviewed_by)

    await events_service.cancel(session, event, reason="Ведущий заболел", by=admin)

    assert event.status is EventStatus.CANCELLED
    assert "delete_topic" in bot.kinds()
    await session.refresh(application)
    assert application.topic_id is None


async def test_held_event_deletes_topic(session, bot):
    application = await setup_application(session)
    await service.open_room(session, application, actor_id=None)
    event = await approve(session, application)
    slot = EventSlot(
        event_id=event.id,
        starts_at=datetime.now(UTC) - timedelta(days=3),
        duration_minutes=90,
    )
    session.add(slot)
    await session.flush()
    event.slot_id = slot.id
    event.status = EventStatus.SCHEDULED
    await session.commit()

    assert await jobs.close_past_events(session) == 1

    assert "delete_topic" in bot.kinds()
    await session.refresh(application)
    assert application.topic_id is None
    # Повторный проход ничего не трогает.
    calls = len(bot.calls)
    await jobs.close_past_events(session)
    assert len(bot.calls) == calls


def test_candidates_handle_ids_pasted_without_prefix():
    """Идентификатор супергруппы часто копируют без приставки -100 — это не
    повод отвечать «чат не найден» и оставлять человека гадать."""
    assert rooms.candidates(-1001234567890) == [-1001234567890]
    assert rooms.candidates(4475231590) == [-1004475231590, 4475231590]
    assert rooms.candidates(-4475231590) == [-4475231590, -1004475231590]
    # Ноль — это не чат, а незаполненное поле.
    assert rooms.candidates(0) == []


def test_topic_link_uses_internal_chat_id():
    assert rooms.topic_link(-1001234567890, 17) == "https://t.me/c/1234567890/17"
    assert rooms.topic_link(-1001234567890, None) is None


async def test_group_without_topics_is_not_saved(session, bot):
    """Обычная группа вместо форума — понятная ошибка, а не мёртвая запись."""
    bot.is_forum = False

    with pytest.raises(rooms.RoomNotReady) as failure:
        await rooms.register(session, -1001234567890, None, added_by=None)
    assert "темы" in str(failure.value)

    left = (
        await session.execute(sa.select(sa.func.count()).select_from(MeetingRoom))
    ).scalar_one()
    assert left == 0


async def test_forget_unlinks_applications(session, bot):
    """Отключённый форум отвязывается от заявок, а не оставляет их со ссылкой
    в никуда."""
    application = await setup_application(session)
    await service.open_room(session, application, actor_id=None)
    room = await session.get(MeetingRoom, application.room_id)

    await rooms.forget(session, room)

    await session.refresh(application)
    assert application.room_id is None
    assert application.topic_id is None
    assert await session.get(MeetingRoom, room.id) is None
