"""Один экземпляр бота на процесс.

Нужен не только самому боту: API тоже ходит в Telegram — переименовать
переговорку, выпустить ссылку, выселить гостя. Клиент один и ленивый, чтобы
приложение поднималось и без токена (тогда просто не работают эти операции).
"""

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties

from app.config import get_config

_bot: Bot | None = None


class BotUnavailable(RuntimeError):
    """Токен не задан — операция в Telegram невозможна."""


def get_bot() -> Bot:
    global _bot
    if _bot is None:
        token = get_config().telegram_bot_token
        if not token:
            raise BotUnavailable("TELEGRAM_BOT_TOKEN не задан")
        _bot = Bot(token=token, default=DefaultBotProperties(parse_mode="HTML"))
    return _bot


async def aclose() -> None:
    global _bot
    if _bot is not None:
        await _bot.session.close()
        _bot = None
