"""Telegram-бот литклуба.

Пускает в Mini App, знакомит с клубом, принимает код присутствия и разгребает
очередь уведомлений. Отдельная его работа — переговорки: бот запоминает id
сообщений в них, чтобы потом вычистить чат перед следующим кандидатом. Для
этого у бота должен быть выключен privacy mode (@BotFather → Bot Settings →
Group Privacy → Turn off), иначе сообщений участников он просто не увидит.

Запуск: ./venv/bin/python -m app.bot
"""

import asyncio
import logging
from pathlib import Path

import sqlalchemy as sa
from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    MenuButtonWebApp,
    Message,
    WebAppInfo,
)

from app.config import get_config
from app.db import SessionLocal
from app.models import Event, Notification, User
from app.models.enums import AttendanceMethod, EventStatus
from app.services import events as events_service
from app.services import jobs, notify, rooms

logger = logging.getLogger(__name__)

# Как часто перечитывать .env в поисках нового адреса туннеля.
URL_WATCH_INTERVAL_SECONDS = 5

# Очередь уведомлений разгребается часто: приглашение в переговорку должно
# приходить сразу, а не через минуты.
NOTIFY_INTERVAL_SECONDS = 5

# Дедлайны и напоминания. Окно допуска в jobs.py — полчаса, поэтому проход раз
# в пять минут ничего не пропускает.
JOBS_INTERVAL_SECONDS = 300

WELCOME = (
    "<b>Литклуб</b>\n\n"
    "Здесь живёт читательский дневник и афиша встреч.\n\n"
    "📚 Отмечайте прочитанное и ставьте оценки.\n"
    "🙋 На карточке книги жмите «Хочу встречу» и выбирайте формат — балаган, "
    "круглый стол, детективную студию.\n"
    "📅 Когда по книге набирается спрос, кто-нибудь берётся её провести — "
    "и вы выбираете удобное время.\n\n"
    "Открывайте приложение кнопкой ниже."
)

HELP = (
    "<b>Что умеет бот</b>\n\n"
    "/app — открыть приложение\n"
    "/code XXXX — отметиться на встрече кодом, который называет ведущий\n"
    "/help — эта справка\n\n"
    "Всё остальное — в приложении: книги, дневник, афиша, профиль."
)

NO_URL = (
    "Приложение пока не подключено: администратор ещё не указал адрес Mini App. "
    "Загляните позже."
)


def current_miniapp_url() -> str:
    """Адрес читается из .env заново, а не из кэша конфига: в разработке он
    меняется при каждом перезапуске туннеля."""
    get_config.cache_clear()
    return get_config().miniapp_url.strip()


def app_keyboard(url: str, text: str = "Открыть литклуб") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=text, web_app=WebAppInfo(url=url))]]
    )


def build_dispatcher() -> Dispatcher:
    dispatcher = Dispatcher()

    @dispatcher.message(CommandStart())
    async def start(message: Message) -> None:
        url = current_miniapp_url()
        async with SessionLocal() as session:
            await session.execute(
                sa.update(User)
                .where(User.tg_id == message.from_user.id, User.onboarded_at.is_(None))
                .values(onboarded_at=sa.func.now())
            )
            await session.commit()
        await message.answer(WELCOME, reply_markup=app_keyboard(url) if url else None)
        if not url:
            await message.answer(NO_URL)

    @dispatcher.message(Command("help"))
    async def help_command(message: Message) -> None:
        await message.answer(HELP)

    @dispatcher.message(Command("app"))
    async def app_command(message: Message) -> None:
        url = current_miniapp_url()
        if not url:
            await message.answer(NO_URL)
            return
        await message.answer("Литклуб:", reply_markup=app_keyboard(url))

    @dispatcher.message(Command("code"))
    async def code_command(message: Message) -> None:
        """Отметка присутствия кодом.

        Дублирует кнопку в приложении намеренно: на встрече проще написать
        боту четыре буквы, чем искать нужный экран.
        """
        parts = (message.text or "").split(maxsplit=1)
        code = parts[1].strip().upper() if len(parts) > 1 else ""
        if not code:
            await message.answer("Напишите так: <code>/code ABCD</code>")
            return

        async with SessionLocal() as session:
            user = (
                await session.execute(sa.select(User).where(User.tg_id == message.from_user.id))
            ).scalar_one_or_none()
            if user is None:
                await message.answer("Сначала откройте приложение — оно заведёт вам профиль.")
                return

            event = (
                await session.execute(
                    sa.select(Event).where(
                        Event.status == EventStatus.SCHEDULED,
                        sa.func.upper(Event.attendance_code) == code,
                    )
                )
            ).scalar_one_or_none()
            if event is None:
                await message.answer("Код не подошёл. Проверьте, что назвал ведущий.")
                return

            await events_service.mark_attendance(
                session, event, user.id, AttendanceMethod.CODE
            )
        await message.answer("Отметил вас на встрече. Хорошего вечера!")

    @dispatcher.message(F.chat.type.in_({"group", "supergroup"}))
    async def remember_room_message(message: Message) -> None:
        """Запоминает сообщения переговорок, чтобы потом их удалить.

        Сообщения чужих чатов сюда не попадут: rooms.remember молча выходит,
        если чата нет в пуле.
        """
        async with SessionLocal() as session:
            await rooms.remember(session, message.chat.id, message.message_id)

    return dispatcher


async def apply_menu_button(bot: Bot, url: str) -> None:
    await bot.set_chat_menu_button(
        menu_button=MenuButtonWebApp(text="Литклуб", web_app=WebAppInfo(url=url))
    )
    logger.info("Кнопка меню обновлена: %s", url)


async def watch_miniapp_url(bot: Bot, initial: str) -> None:
    """Следит за .env и переставляет кнопку меню, когда адрес сменился."""
    known = initial
    while True:
        await asyncio.sleep(URL_WATCH_INTERVAL_SECONDS)
        url = current_miniapp_url()
        if url and url != known:
            known = url
            try:
                await apply_menu_button(bot, url)
            except Exception:
                # Сеть до Telegram могла моргнуть — попробуем на следующем круге.
                logger.exception("Не удалось обновить кнопку меню")


def notify_keyboard(payload: dict) -> InlineKeyboardMarkup | None:
    """Кнопка «открыть» ведёт прямо к нужному экрану приложения."""
    url = current_miniapp_url()
    if not url:
        return None
    if event_id := payload.get("event_id"):
        return app_keyboard(f"{url}?event={event_id}", "Открыть встречу")
    if book_id := payload.get("book_id"):
        return app_keyboard(f"{url}?book={book_id}", "Открыть книгу")
    if payload.get("application_id"):
        return app_keyboard(f"{url}?tab=profile", "Открыть приложение")
    return app_keyboard(url)


async def deliver(bot: Bot, notification: Notification, chat_id: int) -> None:
    text = notify.render(notification.kind, notification.payload or {})
    if text is None:
        notification.failed_reason = "нет шаблона"
        return
    try:
        await bot.send_message(
            chat_id, text, reply_markup=notify_keyboard(notification.payload or {})
        )
        notification.sent_at = sa.func.now()
    except TelegramAPIError as exc:
        # Заблокировавший бота — не повод повторять вечно: помечаем и идём дальше.
        logger.info("Не доставлено пользователю %s: %s", notification.user_id, exc)
        notification.failed_reason = str(exc)[:500]


async def notification_loop(bot: Bot) -> None:
    while True:
        try:
            async with SessionLocal() as session:
                queue = await notify.pending(session)
                for notification in queue:
                    user = await session.get(User, notification.user_id)
                    if user is None or user.tg_id is None:
                        notification.failed_reason = "нет получателя"
                        continue
                    await deliver(bot, notification, user.tg_id)
                if queue:
                    await session.commit()
        except Exception:
            logger.exception("Сбой в очереди уведомлений")
        await asyncio.sleep(NOTIFY_INTERVAL_SECONDS)


async def jobs_loop() -> None:
    while True:
        try:
            async with SessionLocal() as session:
                done = await jobs.run_all(session)
            if any(done.values()):
                logger.info("Фоновые задачи: %s", done)
        except Exception:
            logger.exception("Сбой в фоновых задачах")
        await asyncio.sleep(JOBS_INTERVAL_SECONDS)


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    config = get_config()

    if not config.telegram_bot_token:
        raise SystemExit(
            "TELEGRAM_BOT_TOKEN не задан в .env — получите токен у @BotFather "
            "(/mybots → выберите бота → API Token) и впишите его."
        )
    if not Path("../.env").exists() and not Path(".env").exists():
        logger.warning(".env не найден рядом — читаю только переменные окружения")

    bot = Bot(
        token=config.telegram_bot_token,
        default=DefaultBotProperties(parse_mode="HTML"),
    )
    dispatcher = build_dispatcher()

    me = await bot.get_me()
    url = current_miniapp_url()
    logger.info("Бот @%s запущен. Mini App: %s", me.username, url or "не задан")
    if url:
        await apply_menu_button(bot, url)

    background = [
        asyncio.create_task(watch_miniapp_url(bot, url)),
        asyncio.create_task(notification_loop(bot)),
        asyncio.create_task(jobs_loop()),
    ]
    try:
        # drop_pending_updates: перезапуск в разработке не должен разгребать
        # очередь сообщений, накопившихся, пока бот лежал.
        await dispatcher.start_polling(bot, drop_pending_updates=True)
    finally:
        for task in background:
            task.cancel()


if __name__ == "__main__":
    asyncio.run(main())
