"""Переговорки — темы в форуме оргкомитета.

Бот не умеет создавать чаты (в Bot API нет такого метода), зато умеет
создавать темы в форуме. Поэтому оргкомитет один раз руками заводит супергруппу
с включёнными темами и делает бота администратором, а дальше бот под каждую
заявку открывает свою тему: зовёт кандидата одноразовой ссылкой, держит тему,
пока жива встреча, и удаляет её вместе с перепиской, когда встреча прошла,
отменилась или заявку отклонили.

Раньше вместо форума был пул отдельных супергрупп, и комнату отбирали сразу
при одобрении — ведущему негде было договариваться о встрече, а оргкомитету
приходилось держать по чату на заявку.

В форуме каждый участник видит все темы: скрыть одну Telegram не даёт. Так
задумано — там оргкомитет и ведущие. Кандидата бот исключает, когда у того не
остаётся живых тем.

Ни одна ошибка Telegram не должна ронять решение по заявке: одобрение — это
запись в базе, а тема вокруг неё — удобство. Поэтому всё, что уходит в сеть,
обёрнуто и записывается в check_error форума.
"""

import logging
from datetime import UTC, datetime, timedelta

import sqlalchemy as sa
from aiogram.exceptions import TelegramAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Book, MeetingRoom, OrganizerApplication, User
from app.models.enums import RoomStatus, UserRole
from app.services.settings import SettingsService
from app.services.tg import BotUnavailable, get_bot

logger = logging.getLogger(__name__)

# Права, без которых форум бесполезен: заводить темы, звать людей, удалять
# темы с перепиской и исключать тех, у кого дел в форуме не осталось.
REQUIRED_RIGHTS = (
    "can_manage_topics",
    "can_invite_users",
    "can_delete_messages",
    "can_restrict_members",
)

RIGHTS_HINT = (
    "«управление темами», «приглашение пользователей», «удаление сообщений» "
    "и «блокировка пользователей»"
)

# Статусы участника, при которых звать его в форум не нужно.
INSIDE = ("creator", "administrator", "member", "restricted")


def _problem(member, chat) -> str | None:
    if not getattr(chat, "is_forum", False):
        return "В группе не включены темы: Настройки группы → Темы"
    if member.status != "administrator":
        return "Бот не администратор в этой группе"
    missing = [r for r in REQUIRED_RIGHTS if not getattr(member, r, False)]
    return ("Не хватает прав: " + ", ".join(missing)) if missing else None


async def check(session: AsyncSession, room: MeetingRoom) -> str | None:
    """Проверяет, что группа — форум, а бот в ней админ с нужными правами.

    Возвращает текст проблемы или None. Проверка не бросает исключений
    намеренно: её вызывают и из фоновой задачи, где падать некому.
    """
    try:
        bot = get_bot()
        member = await bot.get_chat_member(room.chat_id, (await bot.me()).id)
        chat = await bot.get_chat(room.chat_id)
    except (BotUnavailable, TelegramAPIError) as exc:
        problem = str(exc)
    else:
        problem = _problem(member, chat)

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


class RoomNotReady(RuntimeError):
    """Группа не найдена, не форум или бот в ней без нужных прав."""


async def resolve(chat_id: int) -> tuple[int, str]:
    """Находит группу, где бот может вести темы.

    Возвращает идентификатор и название либо бросает RoomNotReady с тем, что
    именно не так: «не нашёл» и «нашёл, но темы выключены» чинятся по-разному.
    """
    bot = get_bot()
    me = (await bot.me()).id
    problem = None
    for candidate in candidates(chat_id):
        try:
            member = await bot.get_chat_member(candidate, me)
            chat = await bot.get_chat(candidate)
        except TelegramAPIError:
            continue
        problem = _problem(member, chat)
        if problem is None:
            return candidate, chat.title or f"Форум {candidate}"
    raise RoomNotReady(
        problem
        or "Не нашёл такую группу. Проверьте, что бот добавлен в неё администратором. "
        "Идентификатор супергруппы выглядит как -1001234567890."
    )


async def register(
    session: AsyncSession, chat_id: int, title: str | None, added_by: int
) -> MeetingRoom:
    """Подключает форум.

    Форум сохраняется только после того, как бот убедился, что группа
    существует, темы в ней включены и права у него есть: заведомо мёртвая
    запись в базе ничем не лучше её отсутствия.
    """
    try:
        resolved_id, chat_title = await resolve(chat_id)
    except BotUnavailable as exc:
        raise RoomNotReady("Бот не настроен: нет токена") from exc

    existing = (
        await session.execute(sa.select(MeetingRoom).where(MeetingRoom.chat_id == resolved_id))
    ).scalar_one_or_none()
    if existing is not None:
        existing.status = RoomStatus.FREE
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
    """Отключает форум.

    Сама группа и темы в ней остаются: бот из неё не выходит и ничего не
    удаляет — система просто перестаёт ею распоряжаться. Заявки отвязываем,
    чтобы они не ссылались на тему, которой бот больше не управляет.
    """
    await session.execute(
        sa.update(OrganizerApplication)
        .where(OrganizerApplication.room_id == room.id)
        .values(room_id=None, topic_id=None, invite_link=None)
    )
    await session.delete(room)
    await session.commit()


async def active_forum(session: AsyncSession) -> MeetingRoom | None:
    """Форум, в котором сейчас открываем темы.

    Обычно он один. Если подключили новый, а старый не отключили, берём самый
    свежий: его только что проверили.
    """
    return (
        await session.execute(
            sa.select(MeetingRoom)
            .where(MeetingRoom.status != RoomStatus.DISABLED, MeetingRoom.check_error.is_(None))
            .order_by(MeetingRoom.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


def topic_link(chat_id: int, topic_id: int | None) -> str | None:
    """Ссылка на тему. Работает для тех, кто уже в группе: t.me/c/… —
    внутренний адрес, по нему не вступают."""
    if topic_id is None:
        return None
    internal = str(chat_id).removeprefix("-100").removeprefix("-")
    return f"https://t.me/c/{internal}/{topic_id}"


def topic_name(book: Book | None, user: User | None) -> str:
    title = (book.title if book else "Заявка")[:80]
    who = user.display_name if user else ""
    return f"{title} — {who}"[:128] if who else title


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
    lines += [
        "",
        "Решение принимается в приложении — здесь только обсуждение. "
        "Тема живёт, пока жива встреча, потом удаляется вместе с перепиской.",
    ]
    return "\n".join(lines)


async def _inside(bot, chat_id: int, tg_id: int) -> bool:
    try:
        member = await bot.get_chat_member(chat_id, tg_id)
    except TelegramAPIError:
        return False
    return member.status in INSIDE


async def open_topic(
    session: AsyncSession, application: OrganizerApplication
) -> MeetingRoom | None:
    """Заводит тему под заявку и зовёт туда кандидата.

    Возвращает форум либо None, если рабочего форума нет — тогда вызывающий
    сообщает об этом оргкомитету, а заявка остаётся ждать.
    """
    room = await active_forum(session)
    if room is None:
        return None

    book = await session.get(Book, application.book_id)
    user = await session.get(User, application.user_id)
    ttl = await SettingsService(session).get("invite_link_ttl_hours")

    application.room_id = room.id
    application.chat_opened_at = datetime.now(UTC)
    await session.flush()

    try:
        bot = get_bot()
        topic = await bot.create_forum_topic(room.chat_id, topic_name(book, user))
        application.topic_id = topic.message_thread_id
        await bot.send_message(
            room.chat_id, _card(application, book, user), message_thread_id=topic.message_thread_id
        )
        # Кто уже в форуме (ведёт другую встречу или сам из оргкомитета),
        # тому ссылка не нужна — хватит ссылки на тему.
        if user is None or not await _inside(bot, room.chat_id, user.tg_id):
            link = await bot.create_chat_invite_link(
                room.chat_id,
                name=f"Заявка {application.id}",
                member_limit=1,
                expire_date=datetime.now(UTC) + timedelta(hours=ttl),
            )
            application.invite_link = link.invite_link
    except (BotUnavailable, TelegramAPIError) as exc:
        # Заявку к форуму не привязываем намертво: пока темы нет, оргкомитет
        # может починить права и открыть её ещё раз.
        logger.warning("Не удалось открыть тему в %s: %s", room.chat_id, exc)
        room.check_error = str(exc)

    await session.commit()
    await session.refresh(room)
    return room


async def post(session: AsyncSession, application: OrganizerApplication, text: str) -> None:
    """Пишет в тему заявки. Нет темы — молча ничего: это подсказка, не дело."""
    if application.topic_id is None or application.room_id is None:
        return
    room = await session.get(MeetingRoom, application.room_id)
    if room is None:
        return
    try:
        await get_bot().send_message(room.chat_id, text, message_thread_id=application.topic_id)
    except (BotUnavailable, TelegramAPIError) as exc:
        logger.info("Не удалось написать в тему %s: %s", application.topic_id, exc)


async def close_topic(session: AsyncSession, application: OrganizerApplication) -> None:
    """Удаляет тему заявки вместе с перепиской и, если кандидату в форуме
    больше нечего делать, исключает его.

    Идемпотентна: вызывается и из решений по заявке, и из фоновой задачи.
    Если тему уже удалили руками, Telegram ответит ошибкой — это не повод
    оставлять заявку привязанной к пустому месту.
    """
    if application.topic_id is None or application.room_id is None:
        return
    room = await session.get(MeetingRoom, application.room_id)
    topic_id = application.topic_id
    application.topic_id = None
    application.invite_link = None
    await session.flush()

    if room is not None:
        candidate = await session.get(User, application.user_id)
        still_busy = (
            await session.execute(
                sa.select(sa.func.count()).where(
                    OrganizerApplication.user_id == application.user_id,
                    OrganizerApplication.room_id == room.id,
                    OrganizerApplication.topic_id.is_not(None),
                )
            )
        ).scalar_one()
        try:
            bot = get_bot()
            try:
                await bot.delete_forum_topic(room.chat_id, topic_id)
            except TelegramAPIError as exc:
                logger.info("Тема %s в %s не удалилась: %s", topic_id, room.chat_id, exc)
            # Оргкомитет из форума не выселяем: он там работает.
            if (
                candidate is not None
                and not still_busy
                and candidate.role.rank < UserRole.ADMIN.rank
            ):
                # Забанить и сразу разбанить — единственный способ выселить: без
                # второго шага человек останется в бане и не сможет вернуться,
                # даже если позже подаст новую заявку.
                await bot.ban_chat_member(room.chat_id, candidate.tg_id)
                await bot.unban_chat_member(room.chat_id, candidate.tg_id, only_if_banned=True)
        except (BotUnavailable, TelegramAPIError) as exc:
            # В check_error не пишем: неудачное выселение одного человека
            # (например, владельца группы) не повод останавливать весь форум.
            logger.warning("Не удалось прибрать тему %s в %s: %s", topic_id, room.chat_id, exc)

    await session.commit()
