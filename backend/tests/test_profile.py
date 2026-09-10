"""Анкета: обязательная часть в боте, необязательная в приложении."""

import pytest

from app.models.enums import MemberKind
from app.services import profiles
from tests.conftest import CU_EMAIL, auth, login, member, register

# --- Правила, общие для бота и приложения ------------------------------------


def test_email_required_only_for_students():
    """Почту просим у бакалавров и магистрантов. У абитуриента её ещё нет,
    у сотрудника она другая, у гостя её не бывает вовсе."""
    assert profiles.email_required(MemberKind.BACHELOR)
    assert profiles.email_required(MemberKind.MASTER)
    assert not profiles.email_required(MemberKind.APPLICANT)
    assert not profiles.email_required(MemberKind.STAFF)
    assert not profiles.email_required(MemberKind.GUEST)


def test_name_must_look_like_a_name():
    assert profiles.clean_name("  Иванов   Иван  ") == "Иванов Иван"
    with pytest.raises(profiles.ProfileError):
        profiles.clean_name("")
    with pytest.raises(profiles.ProfileError):
        profiles.clean_name("я")


def test_only_cu_domain_is_accepted():
    assert profiles.clean_email(MemberKind.BACHELOR, " Ivanov@Edu.CentralUniversity.ru ") == (
        "ivanov@edu.centraluniversity.ru"
    )
    with pytest.raises(profiles.ProfileError) as wrong:
        profiles.clean_email(MemberKind.BACHELOR, "ivanov@gmail.com")
    assert "centraluniversity" in str(wrong.value)

    with pytest.raises(profiles.ProfileError):
        profiles.clean_email(MemberKind.MASTER, None)
    # А гостю почта не нужна вовсе.
    assert profiles.clean_email(MemberKind.GUEST, None) is None


# --- Через приложение --------------------------------------------------------


async def test_gate_blocks_until_registration(client):
    token = await login(client, 1001, "Без анкеты")

    # Справочники обязаны работать до регистрации — иначе нечем нарисовать
    # форму правки.
    reference = await client.get("/api/profile/reference", headers=auth(token))
    assert reference.status_code == 200
    assert [k["key"] for k in reference.json()["kinds"]] == [
        "applicant",
        "bachelor",
        "master",
        "staff",
        "guest",
    ]
    assert reference.json()["email_domains"] == ["edu.centraluniversity.ru"]

    # А книги до регистрации не показываем.
    assert (await client.get("/api/books", headers=auth(token))).status_code == 403

    await register(client, token, full_name="Теперь С Анкетой")
    assert (await client.get("/api/books", headers=auth(token))).status_code == 200


async def test_identity_is_editable_with_the_same_rules(client):
    token = await member(client, 1002, "Иванов Иван")

    updated = await client.put(
        "/api/profile/identity",
        json={
            "member_kind": "master",
            "full_name": "Иванов Иван",
            "university_email": "new@edu.centraluniversity.ru",
        },
        headers=auth(token),
    )
    assert updated.status_code == 200
    assert updated.json()["member_kind"] == "master"
    assert updated.json()["member_kind_title"] == "Магистрант"

    # Сменил роль на студенческую без почты — сохранение не проходит.
    broken = await client.put(
        "/api/profile/identity",
        json={"member_kind": "bachelor", "full_name": "Иванов Иван"},
        headers=auth(token),
    )
    assert broken.status_code == 400


async def test_preferences_are_all_skippable(client):
    """Любой вопрос можно пропустить: неотвеченный честнее выдуманного."""
    token = await member(client, 1003, "Молчаливый Участник")

    before = (await client.get("/api/profile", headers=auth(token))).json()
    assert before["needs_preferences"] is True

    saved = await client.put("/api/profile/preferences", json={}, headers=auth(token))
    assert saved.status_code == 200
    body = saved.json()
    assert body["reading_pace"] is None
    assert body["genres"] == []
    # Спросили и получили ответ — пусть и пустой. Напоминать больше не о чем.
    assert body["preferences_at"] is not None
    assert body["needs_preferences"] is False


async def test_preferences_keep_known_values_only(client):
    token = await member(client, 1004, "Разборчивый Участник")
    saved = await client.put(
        "/api/profile/preferences",
        json={
            "reading_pace": "none",
            "club_experience": "organizer",
            "genres": ["Фантастика", "Такого жанра нет"],
        },
        headers=auth(token),
    )
    assert saved.status_code == 200
    assert saved.json()["reading_pace"] == "none"
    assert saved.json()["genres"] == ["Фантастика"]


async def test_preferences_need_registration_first(client):
    token = await login(client, 1005, "Пришёл мимо бота")
    response = await client.put("/api/profile/preferences", json={}, headers=auth(token))
    assert response.status_code == 403
    assert "бот" in response.json()["detail"].lower()


async def test_reminder_can_be_hidden_and_dismissed(client):
    """Крестик прячет плашку до следующего /start, «больше не предупреждать» —
    навсегда."""
    token = await member(client, 1006, "Отмахнувшийся Участник")

    await client.post("/api/profile/dismiss-reminder", json={"forever": False}, headers=auth(token))
    assert (await client.get("/api/profile", headers=auth(token))).json()[
        "needs_preferences"
    ] is False

    # Запуск бота снимает временное скрытие.
    from app.db import get_session
    from app.main import app
    from app.services import profiles as service

    session = app.dependency_overrides[get_session]()
    profile = (await client.get("/api/profile", headers=auth(token))).json()
    assert profile["full_name"] == "Отмахнувшийся Участник"
    user_id = (await _user_id(client, token))
    await service.unhide_reminder(session, user_id)
    assert (await client.get("/api/profile", headers=auth(token))).json()[
        "needs_preferences"
    ] is True

    await client.post("/api/profile/dismiss-reminder", json={"forever": True}, headers=auth(token))
    await service.unhide_reminder(session, user_id)
    assert (await client.get("/api/profile", headers=auth(token))).json()[
        "needs_preferences"
    ] is False


async def _user_id(client, token: str) -> int:
    return (await client.get("/api/auth/me", headers=auth(token))).json()["id"]


async def test_guest_registers_without_email(client):
    token = await login(client, 1007, "Внешний Гость")
    await register(client, token, member_kind="guest", email=None, full_name="Внешний Гость")
    profile = (await client.get("/api/profile", headers=auth(token))).json()
    assert profile["member_kind"] == "guest"
    assert profile["university_email"] is None
    assert profile["email_required"] is False
    assert profile["full_name"] == "Внешний Гость"


async def test_registration_survives_repeat_without_losing_preferences(client):
    """Перепройти знакомство можно — предпочтения при этом не теряются."""
    token = await member(client, 1008, "Повторяющийся Участник")
    await client.put(
        "/api/profile/preferences", json={"genres": ["Классика"]}, headers=auth(token)
    )

    await register(client, token, full_name="Повторяющийся Участник", member_kind="master")
    profile = (await client.get("/api/profile", headers=auth(token))).json()
    assert profile["member_kind"] == "master"
    assert profile["genres"] == ["Классика"]
    assert profile["needs_preferences"] is False
    assert CU_EMAIL == "student@edu.centraluniversity.ru"


def test_empty_init_data_says_what_happened():
    """Пустая строка — это «до подписи не добрались», а не «подпись битая».
    Текст ошибки читает человек в приложении, и он должен подсказывать шаг."""
    from app.core.telegram_auth import InitDataError, parse_init_data

    with pytest.raises(InitDataError) as failure:
        parse_init_data("", "123:TOKEN")
    assert "не передал данные входа" in str(failure.value)

    with pytest.raises(InitDataError) as broken:
        parse_init_data("user=%7B%7D&auth_date=1", "123:TOKEN")
    assert "подписи" in str(broken.value)
