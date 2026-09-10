"""Пул «переговорок» — чатов, в которых оргкомитет обсуждает заявки.

Бот не умеет создавать чаты: в Bot API нет такого метода, и добавлять людей
в чат он тоже не может. Поэтому оргкомитет один раз руками заводит несколько
пустых супергрупп и делает бота администратором, а бот раздаёт их заявкам:
переименовывает, зовёт кандидата одноразовой ссылкой, по завершении выселяет
его и вычищает переписку.

Ни одна ошибка Telegram не должна ронять решение по заявке: одобрение — это
запись в базе, а чат вокруг неё — удобство. Поэтому всё, что уходит в сеть,
обёрнуто и записывается в check_error комнаты.
"""

import logging
from datetime import UTC, datetime, timedelta

import sqlalchemy as sa
from aiogram.exceptions import TelegramAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Book, MeetingRoom, OrganizerApplication, RoomMessage, User
from app.models.enums import RoomStatus
from app.services.settings import SettingsService
from app.services.tg import BotUnavailable, get_bot

logger = logging.getLogger(__name__)

# Права, без которых комната бесполезна: переименовать, позвать, вычистить.
REQUIRED_RIGHTS = ("can_change_info", "can_invite_users", "can_delete_messages")


async def check(session: AsyncSession, room: MeetingRoom) -> str | None:
    """Проверяет, что бот в комнате админ с нужными правами.

    Возвращает текст проблемы или None. Проверка не бросает исключений
    намеренно: её вызывают и из фоновой задачи, где падать некому.
    """
    try:
        bot = get_bot()
        member = await bot.get_chat_member(room.chat_id, (await bot.me()).id)
    except (BotUnavailable, TelegramAPIError) as exc:
        problem = str(exc)
    else:
        if member.status != "administrator":
            problem = "Бот не администратор в этом чате"
        else:
            missing = [r for r in REQUIRED_RIGHTS if not getattr(member, r, False)]
            problem = ("Не хватает прав: " + ", ".join(missing)) if missing else None

    room.check_error = problem
    room.checked_at = datetime.now(UTC)
    await session.commit()
    return problem


def candidates(chat_id: int) -> list[int]:
    """Во что мог превратиться идентификатор по дороге из Telegram.

    У супергрупп он отрицательный и начинается с -100, но в интерфейсах его
    часто показывают без этой приставки, а кто-то копирует уже с минусом.
    Перебираем осмысленные варианты, вместо того чтобы отвечать «чат не найден»
    и оставлять человека гадать, что он сделал не так.
    """
    if chat_id == 0:
        return []
    if chat_id < 0:
        # -1001234567890 — уже полный вид; -1234567890 — минус есть, приставки нет.
        return [chat_id] if str(chat_id).startswith("-100") else [chat_id, int(f"-100{-chat_id}")]
    return [int(f"-100{chat_id}"), chat_id]


async def resolve(chat_id: int) -> tuple[int, str] | None:
    """Находит чат, где бот действительно администратор с нужными правами.

    Возвращает найденный идентификатор и название либо None.
    """
    bot = get_bot()
    me = (await bot.me()).id
    for candidate in candidates(chat_id):
        try:
            member = await bot.get_chat_member(candidate, me)
            if member.status != "administrator":
                continue
            if any(not getattr(member, right, False) for right in REQUIRED_RIGHTS):
                continue
            chat = await bot.get_chat(candidate)
            return candidate, chat.title or f"Переговорка {candidate}"
        except TelegramAPIError:
            continue
    return None


class RoomNotReady(RuntimeError):
    """Чат не найден или бот в нём не администратор — заводить нечего."""


async def register(
    session: AsyncSession, chat_id: int, title: str | None, added_by: int
) -> MeetingRoom:
    """Заводит комнату в пуле.

    Комната сохраняется только после того, как бот убедился, что чат
    существует и он в нём администратор с правами на переименование,
    приглашение и удаление сообщений. Раньше запись создавалась в любом
    случае — и пул засорялся комнатами, которые никогда не заработают.
    """
    try:
        found = await resolve(chat_id)
    except BotUnavailable as exc:
        raise RoomNotReady("Бот не настроен: нет токена") from exc

    if found is None:
        raise RoomNotReady(
            "Не нашёл такой чат или бот в нём не администратор. Проверьте, что: "
            "чат — супергруппа, бот добавлен в неё администратором, и у него есть права "
            "«изменение профиля группы», «приглашение пользователей» и «удаление сообщений». "
            "Идентификатор супергруппы выглядит как -1001234567890."
        )

    resolved_id, chat_title = found
    existing = (
        await session.execute(sa.select(MeetingRoom).where(MeetingRoom.chat_id == resolved_id))
    ).scalar_one_or_none()
    if existing is not None:
        await check(session, existing)
        return existing

    room = MeetingRoom(
        chat_id=resolved_id,
        title=(title or chat_title)[:128],
        added_by=added_by,
        checked_at=datetime.now(UTC),
    )
    session.add(room)
    await session.commit()
    await session.refresh(room)
    return room


async def forget(session: AsyncSession, room: MeetingRoom) -> None:
    """Убирает комнату из пула.

    Сам чат живёт своей жизнью: бот из него не выходит и ничего в нём не
    трогает — система просто перестаёт им распоряжаться. Занятую комнату
    сначала освобождаем, иначе заявка осталась бы со ссылкой в никуда.
    """
    if room.status is RoomStatus.BUSY:
        await release(session, room, kick_user_tg_id=None)
    await session.execute(sa.delete(RoomMessage).where(RoomMessage.room_id == room.id))
    await session.execute(
        sa.update(OrganizerApplication)
        .where(OrganizerApplication.room_id == room.id)
        .values(room_id=None, invite_link=None)
    )
    await session.delete(room)
    await session.commit()


async def free_room(session: AsyncSession) -> MeetingRoom | None:
    """Свободная комната без известных проблем с правами.

    Порядок по id, а не случайный: с одним и тем же чатом оргкомитету проще —
    он привыкает, где обычно идут разговоры.
    """
    return (
        await session.execute(
            sa.select(MeetingRoom)
            .where(MeetingRoom.status == RoomStatus.FREE, MeetingRoom.check_error.is_(None))
            .order_by(MeetingRoom.id)
            .limit(1)
        )
    ).scalar_one_or_none()


async def remember(session: AsyncSession, chat_id: int, message_id: int) -> None:
    """Запоминает сообщение переговорки, чтобы потом её вычистить."""
    room = (
        await session.execute(sa.select(MeetingRoom).where(MeetingRoom.chat_id == chat_id))
    ).scalar_one_or_none()
    if room is None:
        return
    await session.execute(
        sa.dialects.postgresql.insert(RoomMessage)
        .values(room_id=room.id, message_id=message_id)
        .on_conflict_do_nothing(index_elements=["room_id", "message_id"])
    )
    await session.commit()


def _card(application: OrganizerApplication, book: Book | None, user: User | None) -> str:
    lines = [
        "🙋 <b>Заявка на организацию</b>",
        "",
        f"Книга: <b>{book.title if book else '—'}</b>",
        f"Кандидат: {user.display_name if user else '—'}"
        + (f" (@{user.tg_username})" if user and user.tg_username else ""),
    ]
    if application.proposed_type_title:
        lines.append(f"Свой формат: {application.proposed_type_title}")
    if application.answers:
        lines.append("")
        lines.append("<b>Анкета</b>")
        for question, answer in application.answers.items():
            if answer in (None, "", [], {}):
                continue
            if isinstance(answer, list):
                answer = ", ".join(str(a) for a in answer)
            lines.append(f"• {question}: {answer}")
    lines += ["", "Решение принимается в приложении — здесь только обсуждение."]
    return "\n".join(lines)


async def open_chat(session: AsyncSession, application: OrganizerApplication) -> MeetingRoom | None:
    """Занимает комнату под заявку и зовёт туда кандидата.

    Возвращает комнату либо None, если свободных нет — тогда вызывающий
    сообщает об этом оргкомитету, а заявка остаётся ждать.
    """
    room = await free_room(session)
    if room is None:
        return None

    book = await session.get(Book, application.book_id)
    user = await session.get(User, application.user_id)
    settings = SettingsService(session)
    ttl = await settings.get("invite_link_ttl_hours")

    room.status = RoomStatus.BUSY
    room.current_application_id = application.id
    application.room_id = room.id
    application.chat_opened_at = datetime.now(UTC)
    await session.flush()

    try:
        bot = get_bot()
        title = f"{(book.title if book else 'Заявка')[:60]} — {user.display_name if user else ''}"
        await bot.set_chat_title(room.chat_id, title[:128])
        message = await bot.send_message(room.chat_id, _card(application, book, user))
        session.add(RoomMessage(room_id=room.id, message_id=message.message_id))
        link = await bot.create_chat_invite_link(
            room.chat_id,
            name=f"Заявка {application.id}",
            member_limit=1,
            expire_date=datetime.now(UTC) + timedelta(hours=ttl),
        )
        application.invite_link = link.invite_link
    except (BotUnavailable, TelegramAPIError) as exc:
        # Комнату не отпускаем: заявка уже привязана к ней, а починить права
        # и повторить открытие оргкомитет сможет из админки.
        logger.warning("Не удалось открыть переговорку %s: %s", room.chat_id, exc)
        room.check_error = str(exc)

    await session.commit()
    await session.refresh(room)
    return room


async def release(session: AsyncSession, room: MeetingRoom, *, kick_user_tg_id: int | None) -> None:
    """Освобождает комнату: выселяет гостя, отзывает ссылки, чистит переписку.

    Полной гарантии чистоты нет: сообщения, о которых бот не знает, останутся.
    Поэтому в переговорке не обсуждают ничего, чего не должен увидеть
    следующий кандидат, — об этом сказано и в карточке заявки.
    """
    settings = SettingsService(session)
    batch = await settings.get("room_cleanup_batch")

    message_ids = list(
        (
            await session.execute(
                sa.select(RoomMessage.message_id).where(RoomMessage.room_id == room.id)
            )
        )
        .scalars()
        .all()
    )

    try:
        bot = get_bot()
        if kick_user_tg_id is not None:
            # Забанить и сразу разбанить — единственный способ выселить: без
            # второго шага человек останется в бане и не сможет вернуться,
            # даже если позже подаст новую заявку.
            await bot.ban_chat_member(room.chat_id, kick_user_tg_id)
            await bot.unban_chat_member(room.chat_id, kick_user_tg_id, only_if_banned=True)
        for start in range(0, len(message_ids), batch):
            chunk = message_ids[start : start + batch]
            try:
                await bot.delete_messages(room.chat_id, chunk)
            except TelegramAPIError as exc:
                logger.info("Часть сообщений не удалилась в %s: %s", room.chat_id, exc)
        await bot.set_chat_title(room.chat_id, room.title[:128])
    except (BotUnavailable, TelegramAPIError) as exc:
        logger.warning("Не удалось прибрать переговорку %s: %s", room.chat_id, exc)
        room.check_error = str(exc)

    await session.execute(sa.delete(RoomMessage).where(RoomMessage.room_id == room.id))
    room.status = RoomStatus.FREE
    room.current_application_id = None
    await session.commit()
