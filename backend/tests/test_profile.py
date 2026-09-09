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
            "study_level": "bachelor",
            "program": "design",
            "year": 4,
            "university_email": "new@edu.centraluniversity.ru",
            "reading_pace": "fast",
            "genres": ["Фантастика", "Нет такого жанра"],
        },
        headers=auth(token),
    )
    assert updated.status_code == 200
    body = updated.json()
    assert body["full_name"] == "Новое имя"
    assert body["year"] == 4
    assert body["program"] == "design"
    # Незнакомый жанр молча отброшен: справочник мог обновиться.
    assert body["genres"] == ["Фантастика"]


async def test_email_must_be_in_the_cu_domain(client):
    """Чужая почта не принимается: клуб вузовский, и по домену отличают своих."""
    token = await login(client, 1010, "Со сторонней почтой")
    response = await client.put(
        "/api/profile",
        json={
            "member_kind": "student",
            "full_name": "Со сторонней почтой",
            "study_level": "bachelor",
            "program": "development",
            "year": 2,
            "university_email": "student@gmail.com",
        },
        headers=auth(token),
    )
    assert response.status_code == 400
    assert "centraluniversity" in response.json()["detail"]


async def test_student_needs_a_study_level(client):
    token = await login(client, 1011, "Без ступени")
    response = await client.put(
        "/api/profile",
        json={
            "member_kind": "student",
            "full_name": "Без ступени",
            "university_email": "a@edu.centraluniversity.ru",
        },
        headers=auth(token),
    )
    assert response.status_code == 400
    assert "ступень" in response.json()["detail"].lower()


async def test_master_is_not_asked_about_program(client):
    """У магистрантов направление не спрашивают — и присланное не сохраняют."""
    token = await login(client, 1012, "Магистрант")
    response = await client.put(
        "/api/profile",
        json={
            "member_kind": "student",
            "full_name": "Магистрант",
            "study_level": "master",
            "program": "design",
            "year": 1,
            "university_email": "m@edu.centraluniversity.ru",
        },
        headers=auth(token),
    )
    assert response.status_code == 200
    assert response.json()["study_level"] == "master"
    assert response.json()["program"] is None


async def test_undecided_only_on_the_first_year(client):
    token = await login(client, 1013, "Второкурсник")
    body = {
        "member_kind": "student",
        "full_name": "Второкурсник",
        "study_level": "bachelor",
        "program": "undecided",
        "university_email": "u@edu.centraluniversity.ru",
    }

    first = await client.put("/api/profile", json=body | {"year": 1}, headers=auth(token))
    assert first.status_code == 200
    assert first.json()["program"] == "undecided"

    second = await client.put("/api/profile", json=body | {"year": 2}, headers=auth(token))
    assert second.status_code == 400
    assert "перв" in second.json()["detail"].lower()


async def test_bachelor_needs_a_program(client):
    token = await login(client, 1014, "Без направления")
    response = await client.put(
        "/api/profile",
        json={
            "member_kind": "student",
            "full_name": "Без направления",
            "study_level": "bachelor",
            "year": 1,
            "university_email": "p@edu.centraluniversity.ru",
        },
        headers=auth(token),
    )
    assert response.status_code == 400
    assert "направление" in response.json()["detail"].lower()


async def test_guest_keeps_no_study_fields(client):
    """Ступень и курс у внешнего гостя — мусор, который всплыл бы в аналитике."""
    token = await login(client, 1015, "Гость")
    response = await client.put(
        "/api/profile",
        json={
            "member_kind": "guest",
            "full_name": "Гость",
            "study_level": "bachelor",
            "program": "ai",
            "year": 3,
        },
        headers=auth(token),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["study_level"] is None and body["program"] is None and body["year"] is None


async def test_reference_lists_programs_and_domain(client):
    token = await login(client, 1016, "Смотрящий справочник")
    reference = (await client.get("/api/profile/reference", headers=auth(token))).json()

    keys = [p["key"] for p in reference["programs"]]
    assert keys == ["development", "ai", "business", "design", "undecided"]
    # Клиент должен знать, какой вариант прятать со второго курса.
    assert [p["key"] for p in reference["programs"] if p["first_year_only"]] == ["undecided"]
    assert reference["email_domains"] == ["edu.centraluniversity.ru"]
