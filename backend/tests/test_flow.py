"""Сквозной сценарий: спрос → заявка → одобрение → слоты → голосование → встреча."""

import sqlalchemy as sa

from app.models import Book, Demand
from app.services.books.normalize import dedup_key
from tests.conftest import SUPERADMIN_TG_ID, auth, member


async def make_book(session, title="Понедельник начинается в субботу", authors=None) -> Book:
    authors = authors or ["Аркадий Стругацкий", "Борис Стругацкий"]
    book = Book(title=title, authors=authors, dedup_key=dedup_key(title, authors))
    session.add(book)
    await session.commit()
    await session.refresh(book)
    return book


async def type_ids(client, token) -> list[int]:
    reference = await client.get("/api/profile/reference", headers=auth(token))
    return [t["id"] for t in reference.json()["event_types"]]


async def test_full_scenario(client, session):
    admin = await member(client, SUPERADMIN_TG_ID, "Оргкомитет")
    reader = await member(client, 2001, "Читатель")
    organizer = await member(client, 2002, "Ведущий")

    book = await make_book(session)
    types = await type_ids(client, reader)

    # 1. Читатель отмечает книгу прочитанной прямо из списка.
    read = await client.post(f"/api/books/{book.id}/read", headers=auth(reader))
    assert read.status_code == 200
    assert read.json()["reading_status"] == "finished"

    # 2. И хочет по ней встречу — в двух форматах.
    demand = await client.post(
        f"/api/books/{book.id}/demand",
        json={"event_type_ids": types[:2]},
        headers=auth(reader),
    )
    assert demand.status_code == 204

    # 3. Спрос виден в нижнем ярусе афиши.
    board = (await client.get("/api/board", headers=auth(organizer))).json()
    assert [d["book"]["title"] for d in board["demands"]] == [book.title]
    assert board["demands"][0]["waiting"] == 1
    assert board["demands"][0]["readers"] == 1  # читатель книгу читал
    assert board["demands"][0]["joined"] is False

    # 4. Второй участник присоединяется к ожидающим, не читая книгу.
    await client.post(
        f"/api/books/{book.id}/demand",
        json={"event_type_ids": types[:1]},
        headers=auth(organizer),
    )
    board = (await client.get("/api/board", headers=auth(organizer))).json()
    assert board["demands"][0]["waiting"] == 2
    assert board["demands"][0]["readers"] == 1
    assert board["demands"][0]["joined"] is True

    # 5. Он же подаёт заявку на организацию.
    application = await client.post(
        "/api/applications",
        json={
            "book_id": book.id,
            "event_type_id": types[0],
            "answers": {
                "read": True,
                "experience": "Пару раз",
                "idea": "Поговорим про НИИЧАВО",
            },
        },
        headers=auth(organizer),
    )
    assert application.status_code == 200, application.text
    application_id = application.json()["id"]
    assert application.json()["status"] == "submitted"

    # Повторная заявка по той же книге отбивается.
    duplicate = await client.post(
        "/api/applications",
        json={
            "book_id": book.id,
            "event_type_id": types[0],
            "answers": {"read": True, "experience": "Нет, впервые", "idea": "И ещё раз"},
        },
        headers=auth(organizer),
    )
    assert duplicate.status_code == 409

    # 6. Оргкомитет одобряет — и задаёт аудиторию.
    approved = await client.post(
        f"/api/applications/{application_id}/approve",
        json={"audience": ["bachelor"], "comment": "Договорились"},
        headers=auth(admin),
    )
    assert approved.status_code == 200, approved.text
    event_id = approved.json()["event_id"]
    assert event_id is not None

    # 7. Организатор расставляет окна.
    slots = await client.post(
        f"/api/events/{event_id}/slots",
        json={
            "slots": [
                {"starts_at": "2026-10-01T18:00:00+03:00", "place": "Библиотека"},
                {"starts_at": "2026-10-03T15:00:00+03:00", "place": "Читальня"},
            ],
            "title": "НИИЧАВО и мы",
            "vote_days": 3,
        },
        headers=auth(organizer),
    )
    assert slots.status_code == 200, slots.text
    assert slots.json()["status"] == "voting"
    slot_ids = [s["id"] for s in slots.json()["slots"]]

    # 8. Участники голосуют за удобные окна.
    await client.post(
        f"/api/events/{event_id}/vote", json={"slot_ids": [slot_ids[1]]}, headers=auth(reader)
    )
    await client.post(
        f"/api/events/{event_id}/vote",
        json={"slot_ids": slot_ids},
        headers=auth(organizer),
    )

    card = (await client.get(f"/api/events/{event_id}", headers=auth(reader))).json()
    votes = {s["id"]: s["votes"] for s in card["slots"]}
    assert votes[slot_ids[1]] == 2
    assert votes[slot_ids[0]] == 1

    # 9. Организатор закрепляет время (право вето — до дедлайна).
    decided = await client.post(
        f"/api/events/{event_id}/decide",
        json={"slot_id": slot_ids[1]},
        headers=auth(organizer),
    )
    assert decided.status_code == 200, decided.text
    assert decided.json()["status"] == "scheduled"
    assert decided.json()["place"] == "Читальня"

    # Спрос по книге закрыт: встреча назначена, ждать больше нечего.
    active_demands = (
        await session.execute(
            sa.select(sa.func.count()).where(
                Demand.book_id == book.id, Demand.revoked_at.is_(None)
            )
        )
    ).scalar_one()
    assert active_demands == 0

    # 10. Запись и присутствие по коду.
    going = await client.post(
        f"/api/events/{event_id}/participation", json={"state": "going"}, headers=auth(reader)
    )
    assert going.json()["going"] == 1

    # Код заранее не выдаём: до встречи ещё месяц, и он бы разошёлся.
    early = await client.get(f"/api/events/{event_id}/code", headers=auth(organizer))
    assert early.status_code == 409
    assert "во время встречи" in early.json()["detail"]

    card = (await client.get(f"/api/events/{event_id}", headers=auth(reader))).json()
    assert card["code_available"] is False

    # 11. Отзыв — только тому, кто был.
    feedback = await client.post(
        f"/api/events/{event_id}/feedback",
        json={"score": 9, "text": "Было живо"},
        headers=auth(reader),
    )
    assert feedback.status_code == 403
    assert "были" in feedback.json()["detail"]


async def test_demand_without_formats_is_enough(client, session):
    """«Хочу встречу» — уже полноценная отметка. Требовать уточнения формата
    значило бы терять тех, кому всё равно, в каком виде обсуждать."""
    reader = await member(client, 2010, "Молчун")
    book = await make_book(session, "Пикник на обочине", ["Стругацкие"])

    response = await client.post(
        f"/api/books/{book.id}/demand", json={"event_type_ids": []}, headers=auth(reader)
    )
    assert response.status_code == 204

    card = (await client.get(f"/api/books/{book.id}", headers=auth(reader))).json()
    assert card["demanded"] is True
    assert card["demand_count"] == 1
    assert card["my_demand_type_ids"] == []

    # Уточнить формат можно позже — той же ручкой.
    types = await type_ids(client, reader)
    await client.post(
        f"/api/books/{book.id}/demand",
        json={"event_type_ids": types[:1]},
        headers=auth(reader),
    )
    card = (await client.get(f"/api/books/{book.id}", headers=auth(reader))).json()
    assert card["my_demand_type_ids"] == types[:1]
    # Отметка осталась одна, а не превратилась во вторую.
    assert card["demand_count"] == 1


async def test_second_read_tap_removes_empty_mark(client, session):
    """Кнопка «Читал» в списке должна сниматься тем же нажатием, но не стирать
    оценку и отзыв, если они уже есть."""
    reader = await member(client, 2011, "Передумавший")
    book = await make_book(session, "Улитка на склоне", ["Стругацкие"])

    await client.post(f"/api/books/{book.id}/read", headers=auth(reader))
    off = await client.post(f"/api/books/{book.id}/read", headers=auth(reader))
    assert off.json()["reading_status"] is None

    await client.put(
        f"/api/books/{book.id}/diary",
        json={"status": "finished", "score": 8},
        headers=auth(reader),
    )
    kept = await client.post(f"/api/books/{book.id}/read", headers=auth(reader))
    assert kept.json()["reading_status"] == "finished"
    assert kept.json()["my_score"] == 8


async def test_only_admin_decides_applications(client, session):
    stranger = await member(client, 2012, "Посторонний")
    organizer = await member(client, 2013, "Ведущий2")
    book = await make_book(session, "Град обреченный", ["Стругацкие"])

    application = await client.post(
        "/api/applications",
        json={
            "book_id": book.id,
            "event_type_id": (await type_ids(client, organizer))[0],
            "answers": {"read": True, "experience": "Регулярно", "idea": "Разберём финал"},
        },
        headers=auth(organizer),
    )
    application_id = application.json()["id"]

    forbidden = await client.post(
        f"/api/applications/{application_id}/approve",
        json={"audience": []},
        headers=auth(stranger),
    )
    assert forbidden.status_code == 403

    # Свою заявку можно отозвать.
    withdrawn = await client.post(
        f"/api/applications/{application_id}/withdraw", headers=auth(organizer)
    )
    assert withdrawn.status_code == 204


async def test_organizer_sees_who_is_going(client, session):
    """Список идущих — с именами из анкеты.

    Тест ходит по-настоящему в ручку: она однажды падала в рантайме, потому
    что обработчик назывался так же, как импортированный рядом модуль, —
    статические проверки этого не видели.
    """
    admin = await member(client, SUPERADMIN_TG_ID, "Оргкомитет Клуба")
    organizer = await member(client, 2100, "Ведущий Встречи")
    reader = await member(client, 2101, "Читатель Клуба")
    book = await make_book(session, "Дом, в котором…", ["Мариам Петросян"])

    application = await client.post(
        "/api/applications",
        json={
            "book_id": book.id,
            "event_type_id": (await type_ids(client, organizer))[0],
            "answers": {"read": True, "experience": "Пару раз", "idea": "Про Дом"},
        },
        headers=auth(organizer),
    )
    approved = await client.post(
        f"/api/applications/{application.json()['id']}/approve",
        json={"audience": []},
        headers=auth(admin),
    )
    event_id = approved.json()["event_id"]

    slots = await client.post(
        f"/api/events/{event_id}/slots",
        json={"slots": [{"starts_at": "2026-12-01T18:00:00+03:00"}]},
        headers=auth(organizer),
    )
    await client.post(
        f"/api/events/{event_id}/decide",
        json={"slot_id": slots.json()["slots"][0]["id"]},
        headers=auth(organizer),
    )
    await client.post(
        f"/api/events/{event_id}/participation", json={"state": "going"}, headers=auth(reader)
    )

    people = await client.get(f"/api/events/{event_id}/people", headers=auth(organizer))
    assert people.status_code == 200, people.text
    assert people.json() == [
        {"id": people.json()[0]["id"], "name": "Читатель Клуба", "state": "going"}
    ]

    # Посторонний список не видит: кто идёт — дело организатора.
    stranger = await client.get(f"/api/events/{event_id}/people", headers=auth(reader))
    assert stranger.status_code == 403
