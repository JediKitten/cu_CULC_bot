"""Фильтр аудитории: встреча «только для студентов» не должна протекать наружу."""

from tests.conftest import SUPERADMIN_TG_ID, auth, guest, member
from tests.test_flow import make_book, type_ids


async def approved_event(client, session, *, audience: list[str]) -> int:
    admin = await member(client, SUPERADMIN_TG_ID, "Оргкомитет")
    organizer = await member(client, 3001, "Ведущий")
    book = await make_book(session, "Солярис", ["Станислав Лем"])

    application = await client.post(
        "/api/applications",
        json={
            "book_id": book.id,
            "event_type_id": (await type_ids(client, organizer))[0],
            "answers": {"read": True, "experience": "Пару раз", "idea": "Океан как герой"},
        },
        headers=auth(organizer),
    )
    approved = await client.post(
        f"/api/applications/{application.json()['id']}/approve",
        json={"audience": audience},
        headers=auth(admin),
    )
    event_id = approved.json()["event_id"]

    await client.post(
        f"/api/events/{event_id}/slots",
        json={"slots": [{"starts_at": "2026-11-05T18:00:00+03:00"}]},
        headers=auth(organizer),
    )
    return event_id


async def test_guest_does_not_see_students_only_event(client, session):
    event_id = await approved_event(client, session, audience=["bachelor"])
    outsider = await guest(client, 3002, "Гость")

    board = (await client.get("/api/board", headers=auth(outsider))).json()
    assert [e["id"] for e in board["events"]] == []

    # И по прямой ссылке тоже: существование закрытой встречи — тоже сведения.
    direct = await client.get(f"/api/events/{event_id}", headers=auth(outsider))
    assert direct.status_code == 404


async def test_guest_cannot_vote_or_join_students_only_event(client, session):
    event_id = await approved_event(client, session, audience=["bachelor"])
    outsider = await guest(client, 3003, "Гость2")

    vote = await client.post(
        f"/api/events/{event_id}/vote", json={"slot_ids": []}, headers=auth(outsider)
    )
    assert vote.status_code == 404

    join = await client.post(
        f"/api/events/{event_id}/participation", json={"state": "going"}, headers=auth(outsider)
    )
    assert join.status_code == 404


async def test_student_sees_students_only_event(client, session):
    event_id = await approved_event(client, session, audience=["bachelor"])
    student = await member(client, 3004, "Студентка")

    board = (await client.get("/api/board", headers=auth(student))).json()
    assert event_id in [e["id"] for e in board["events"]]


async def test_empty_audience_means_everyone(client, session):
    event_id = await approved_event(client, session, audience=[])
    outsider = await guest(client, 3005, "Гость3")

    board = (await client.get("/api/board", headers=auth(outsider))).json()
    assert event_id in [e["id"] for e in board["events"]]
