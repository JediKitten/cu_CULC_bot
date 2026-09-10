"""Регистрация в боте: имя, роль, почта.

Раньше анкету спрашивало Mini App, и человек попадал в пустое приложение,
не понимая, что это и зачем. Теперь знакомство идёт разговором в боте —
три вопроса, — а вкусы и предпочтения предлагаются уже внутри приложения
и необязательны.

Состояние диалога держит FSM aiogram: она живёт в памяти процесса, и это
осознанный размен. Перезапуск бота обрывает незаконченную регистрацию, но
она короткая, а альтернатива — хранить полуответы в базе и разбираться,
что с ними делать через неделю.
"""

import logging

import sqlalchemy as sa
from aiogram import F, Router
from aiogram.filters import Command, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    WebAppInfo,
)

from app.db import SessionLocal
from app.models import Profile, User
from app.models.enums import MemberKind
from app.services import profiles

logger = logging.getLogger(__name__)

router = Router()

WELCOME = (
    "<b>Литклуб ЦУ</b>\n\n"
    "Здесь ведут читательский дневник, собирают спрос на обсуждения и "
    "договариваются о встречах.\n\n"
    "Давайте знакомиться — три коротких вопроса."
)

ASK_NAME = "1/3. Как вас зовут? Напишите <b>фамилию и имя</b>."
ASK_KIND = "2/3. Кто вы в вузе?"
ASK_EMAIL = (
    "3/3. Напишите вашу студенческую почту — она в домене "
    f"<code>@{profiles.CU_EMAIL_DOMAINS[0]}</code>."
)

ABOUT = (
    "Готово, вы в клубе.\n\n"
    "<b>Что здесь есть</b>\n"
    "📚 <b>Книги</b> — поиск, читательский дневник, оценки и отзывы.\n"
    "🙋 <b>Хочу встречу</b> — отметка на карточке книги. Когда таких набирается "
    "достаточно, оргкомитет ищет ведущего.\n"
    "📅 <b>Афиша</b> — назначенные встречи и книги, которые ждут своей. "
    "Время выбирают голосованием.\n"
    "🎤 <b>Хочу организовать</b> — если готовы провести встречу сами.\n\n"
    "Ещё в приложении можно ответить на несколько необязательных вопросов о "
    "вкусах — что читаете, какие форматы встреч интересны. Это помогает звать "
    "вас на то, что вам подходит. Займёт минуту, и любой вопрос можно пропустить."
)

RESTART_HINT = "Если что-то не так — /start, и пройдём заново."


class Registration(StatesGroup):
    name = State()
    kind = State()
    email = State()


def kind_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=title, callback_data=f"kind:{kind.value}")]
            for kind, title in profiles.KIND_TITLES.items()
        ]
    )


def app_keyboard(url: str, text: str) -> InlineKeyboardMarkup | None:
    if not url:
        return None
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=text, web_app=WebAppInfo(url=url))]]
    )


async def get_profile(tg_id: int) -> tuple[int | None, Profile | None]:
    async with SessionLocal() as session:
        user = (
            await session.execute(sa.select(User).where(User.tg_id == tg_id))
        ).scalar_one_or_none()
        if user is None:
            return None, None
        return user.id, await session.get(Profile, user.id)


async def ensure_user(message: Message) -> int:
    """Заводит аккаунт, если человек пришёл в бота раньше, чем в приложение."""
    async with SessionLocal() as session:
        tg = message.from_user
        user = (
            await session.execute(sa.select(User).where(User.tg_id == tg.id))
        ).scalar_one_or_none()
        if user is None:
            user = User(
                tg_id=tg.id,
                tg_username=tg.username,
                display_name=" ".join(filter(None, (tg.first_name, tg.last_name)))
                or (tg.username or f"user{tg.id}"),
            )
            session.add(user)
        else:
            user.tg_username = tg.username
        user.onboarded_at = user.onboarded_at or sa.func.now()
        await session.commit()
        # Временное скрытие плашки снимается при каждом запуске бота — так
        # человек, который просто отмахнулся крестиком, увидит её снова.
        await profiles.unhide_reminder(session, user.id)
        return user.id


def build_router(miniapp_url: callable) -> Router:
    """Роутер регистрации. Адрес Mini App приходит функцией: в разработке он
    меняется при каждом перезапуске туннеля."""

    @router.message(CommandStart())
    async def start(message: Message, state: FSMContext) -> None:
        await state.clear()
        user_id = await ensure_user(message)
        _, profile = await get_profile(message.from_user.id)

        if profile is not None and profile.completed_at is not None:
            await message.answer(
                f"С возвращением, {profile.full_name}!",
                reply_markup=app_keyboard(miniapp_url(), "Открыть литклуб"),
            )
            if profile.preferences_at is None and not profile.reminder_dismissed:
                await message.answer(
                    "Кстати, в приложении остались необязательные вопросы о вкусах — "
                    "они помогают звать вас на подходящие встречи."
                )
            return

        await state.update_data(user_id=user_id)
        await message.answer(WELCOME)
        await message.answer(ASK_NAME)
        await state.set_state(Registration.name)

    @router.message(Registration.name, F.text)
    async def got_name(message: Message, state: FSMContext) -> None:
        try:
            name = profiles.clean_name(message.text)
        except profiles.ProfileError as exc:
            await message.answer(f"{exc}. Например: Иванов Иван")
            return
        await state.update_data(full_name=name)
        await message.answer(ASK_KIND, reply_markup=kind_keyboard())
        await state.set_state(Registration.kind)

    @router.callback_query(Registration.kind, F.data.startswith("kind:"))
    async def got_kind(call: CallbackQuery, state: FSMContext) -> None:
        kind = MemberKind(call.data.split(":", 1)[1])
        await state.update_data(member_kind=kind.value)
        await call.answer()
        await call.message.edit_text(
            f"{ASK_KIND}\n\n→ {profiles.KIND_TITLES[kind]}", reply_markup=None
        )

        if profiles.email_required(kind):
            await call.message.answer(ASK_EMAIL)
            await state.set_state(Registration.email)
            return
        await finish(call.message, state)

    @router.message(Registration.email, F.text)
    async def got_email(message: Message, state: FSMContext) -> None:
        data = await state.get_data()
        kind = MemberKind(data["member_kind"])
        try:
            profiles.clean_email(kind, message.text)
        except profiles.ProfileError as exc:
            await message.answer(f"{exc}. Попробуйте ещё раз.")
            return
        await state.update_data(university_email=message.text.strip().lower())
        await finish(message, state)

    async def finish(message: Message, state: FSMContext) -> None:
        data = await state.get_data()
        async with SessionLocal() as session:
            try:
                await profiles.register(
                    session,
                    data["user_id"],
                    full_name=data["full_name"],
                    member_kind=MemberKind(data["member_kind"]),
                    university_email=data.get("university_email"),
                )
            except profiles.ProfileError as exc:
                await message.answer(f"{exc}\n\n{RESTART_HINT}")
                await state.clear()
                return

        await state.clear()
        await message.answer(
            ABOUT, reply_markup=app_keyboard(miniapp_url(), "Открыть литклуб")
        )

    @router.message(Command("profile"))
    async def profile_command(message: Message, state: FSMContext) -> None:
        """Перепройти знакомство — например, если сменилась роль."""
        await state.clear()
        user_id = await ensure_user(message)
        await state.update_data(user_id=user_id)
        await message.answer(ASK_NAME)
        await state.set_state(Registration.name)

    @router.message(StateFilter(Registration.name, Registration.kind, Registration.email))
    async def wrong_kind_of_answer(message: Message, state: FSMContext) -> None:
        """Не текст там, где ждали текст, — например, стикер вместо имени."""
        current = await state.get_state()
        prompts = {
            Registration.name.state: ASK_NAME,
            Registration.kind.state: ASK_KIND,
            Registration.email.state: ASK_EMAIL,
        }
        await message.answer(
            prompts.get(current, ASK_NAME),
            reply_markup=kind_keyboard() if current == Registration.kind.state else None,
        )

    return router
