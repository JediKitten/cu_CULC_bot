"""Пул переговорок.

Бот не создаёт чаты — он раздаёт заранее заведённые. Проверяем именно эту
механику: занятие, освобождение, отсутствие свободных комнат. Telegram
подменён: тесты не должны ходить в сеть, а нам важно, что именно бот пытается
там сделать.
"""

import pytest
import sqlalchemy as sa

from app.models import Book, MeetingRoom, OrganizerApplication, RoomMessage, User
from app.models.enums import ApplicationStatus, RoomStatus
from app.services import applications as service
from app.services import rooms
from app.services.books.normalize import dedup_key


class FakeBot:
    """Записывает вызовы вместо похода в Telegram."""

    def __init__(self) -> None:
        self.calls: list[tuple] = []
        self.message_id = 100

    async def set_chat_title(self, chat_id, title):
        self.calls.append(("title", chat_id, title))

    async def send_message(self, chat_id, text, **kwargs):
        self.message_id += 1
        self.calls.append(("message", chat_id, text))
        return type("Msg", (), {"message_id": self.message_id})()

    async def create_chat_invite_link(self, chat_id, **kwargs):
        self.calls.append(("link", chat_id))
        return type("Link", (), {"invite_link": f"https://t.me/+fake{chat_id}"})()

    async def ban_chat_member(self, chat_id, user_id):
        self.calls.append(("ban", chat_id, user_id))

    async def unban_chat_member(self, chat_id, user_id, only_if_banned=False):
        self.calls.append(("unban", chat_id, user_id))

    async def delete_messages(self, chat_id, message_ids):
        self.calls.append(("delete", chat_id, tuple(message_ids)))


@pytest.fixture
def bot(monkeypatch) -> FakeBot:
    fake = FakeBot()
    monkeypatch.setattr("app.services.rooms.get_bot", lambda: fake)
    return fake


async def setup_application(session, *, rooms_count: int = 1) -> OrganizerApplication:
    title = "Пикник на обочине"
    book = Book(title=title, authors=["Стругацкие"], dedup_key=dedup_key(title, ["Стругацкие"]))
    user = User(tg_id=4242, display_name="Кандидат", tg_username="candidate")
    session.add_all([book, user])
    await session.flush()

    for index in range(rooms_count):
        session.add(MeetingRoom(chat_id=-100_000 - index, title=f"Переговорка {index + 1}"))

    application = OrganizerApplication(
        user_id=user.id,
        book_id=book.id,
        answers={"Вы читали эту книгу?": True},
    )
    session.add(application)
    await session.commit()
    await session.refresh(application)
    return application


async def test_open_chat_occupies_a_room_and_invites(session, bot):
    application = await setup_application(session)

    room = await rooms.open_chat(session, application)

    assert room is not None
    assert room.status is RoomStatus.BUSY
    assert room.current_application_id == application.id
    assert application.invite_link.startswith("https://t.me/+fake")

    kinds = [call[0] for call in bot.calls]
    assert kinds == ["title", "message", "link"]
    # Название чата говорит, о чём он: книга и кандидат.
    assert "Пикник" in bot.calls[0][2] and "Кандидат" in bot.calls[0][2]


async def test_no_free_room_leaves_application_waiting(session, bot):
    application = await setup_application(session, rooms_count=0)

    assert await rooms.open_chat(session, application) is None
    assert application.status is ApplicationStatus.SUBMITTED


async def test_open_room_twice_does_not_take_a_second_room(session, bot):
    application = await setup_application(session, rooms_count=2)

    await service.open_room(session, application, actor_id=None)
    with pytest.raises(Exception):  # noqa: B017 — важен сам отказ, не его тип
        await service.open_room(session, application, actor_id=None)

    busy = (
        await session.execute(
            sa.select(sa.func.count()).where(MeetingRoom.status == RoomStatus.BUSY)
        )
    ).scalar_one()
    assert busy == 1


async def test_release_kicks_guest_and_cleans_history(session, bot):
    application = await setup_application(session)
    room = await rooms.open_chat(session, application)
    session.add(RoomMessage(room_id=room.id, message_id=500))
    await session.commit()

    candidate = await session.get(User, application.user_id)
    await rooms.release(session, room, kick_user_tg_id=candidate.tg_id)

    kinds = [call[0] for call in bot.calls]
    # Забанить и сразу разбанить — иначе человек остаётся в бане навсегда.
    assert kinds.count("ban") == 1 and kinds.count("unban") == 1
    deleted = next(call for call in bot.calls if call[0] == "delete")
    assert 500 in deleted[2]

    await session.refresh(room)
    assert room.status is RoomStatus.FREE
    assert room.current_application_id is None
    left = (
        await session.execute(
            sa.select(sa.func.count()).where(RoomMessage.room_id == room.id)
        )
    ).scalar_one()
    assert left == 0


async def test_approval_releases_the_room(session, bot):
    """Решение по заявке — запись в базе; чат вокруг неё лишь удобство,
    и он обязан освободиться независимо от того, что ответил Telegram."""
    application = await setup_application(session)
    await service.open_room(session, application, actor_id=None)

    admin = User(tg_id=1, display_name="Админ")
    session.add(admin)
    await session.flush()
    from app.models import EventType

    event_type_id = (
        await session.execute(sa.select(EventType.id).order_by(EventType.id).limit(1))
    ).scalar_one()

    await service.approve(
        session,
        application,
        actor=admin,
        audience=[],
        event_type_id=event_type_id,
        comment=None,
    )

    room = await session.get(MeetingRoom, application.room_id)
    assert room.status is RoomStatus.FREE
