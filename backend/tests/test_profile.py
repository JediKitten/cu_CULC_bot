"""Анкета: категория участника и правило вузовской почты."""

from tests.conftest import auth, login, onboard


async def test_gate_blocks_until_profile_is_filled(client):
    token = await login(client, 1001, "Без анкеты")

    # Справочники обязаны работать до анкеты — иначе её нечем нарисовать.
    reference = await client.get("/api/profile/reference", headers=auth(token))
    assert reference.status_code == 200
    assert reference.json()["event_types"]

    # А вот книги до анкеты не показываем.
    blocked = await client.get("/api/books", headers=auth(token))
    assert blocked.status_code == 403

    await onboard(client, token)
    assert (await client.get("/api/books", headers=auth(token))).status_code == 200


async def test_email_required_for_student(client):
    token = await login(client, 1002, "Студент")
    response = await client.put(
        "/api/profile",
        json={"member_kind": "student", "full_name": "Студент", "university_email": None},
        headers=auth(token),
    )
    assert response.status_code == 400
    assert "почта" in response.json()["detail"].lower()


async def test_email_required_for_staff(client):
    token = await login(client, 1003, "Сотрудник")
    response = await client.put(
        "/api/profile",
        json={"member_kind": "staff", "full_name": "Сотрудник"},
        headers=auth(token),
    )
    assert response.status_code == 400


async def test_email_optional_for_guest_and_applicant(client):
    for tg_id, kind in ((1004, "guest"), (1005, "applicant")):
        token = await login(client, tg_id, kind)
        response = await client.put(
            "/api/profile",
            json={"member_kind": kind, "full_name": "Гость клуба"},
            headers=auth(token),
        )
        assert response.status_code == 200, response.text
        assert response.json()["email_required"] is False


async def test_switching_to_student_without_email_is_rejected(client):
    """Правило работает и при правке профиля, а не только при регистрации."""
    token = await login(client, 1006, "Сначала гость")
    await onboard(client, token, member_kind="guest", email=None)

    response = await client.put(
        "/api/profile",
        json={"member_kind": "student", "full_name": "Сначала гость"},
        headers=auth(token),
    )
    assert response.status_code == 400


async def test_profile_is_editable(client):
    token = await login(client, 1007, "Меняющийся")
    await onboard(client, token)

    updated = await client.put(
        "/api/profile",
        json={
            "member_kind": "student",
            "full_name": "Новое имя",
            "faculty": "Физфак",
            "year": 4,
            "university_email": "new@univer.ru",
            "reading_pace": "fast",
            "genres": ["Фантастика", "Нет такого жанра"],
        },
        headers=auth(token),
    )
    assert updated.status_code == 200
    body = updated.json()
    assert body["full_name"] == "Новое имя"
    assert body["year"] == 4
    # Незнакомый жанр молча отброшен: справочник мог обновиться.
    assert body["genres"] == ["Фантастика"]


async def test_guest_loses_faculty_and_year(client):
    """Курс у внешнего гостя — мусор, который потом всплыл бы в аналитике."""
    token = await login(client, 1008, "Внешний")
    response = await client.put(
        "/api/profile",
        json={
            "member_kind": "guest",
            "full_name": "Внешний",
            "faculty": "Придуманный",
            "year": 3,
        },
        headers=auth(token),
    )
    assert response.status_code == 200
    assert response.json()["faculty"] is None
    assert response.json()["year"] is None
