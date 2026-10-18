"""Встречи глазами оргкомитета: одобренная встреча не теряется из виду,
её можно отменить, а люди об этом узнают."""

import sqlalchemy as sa

from app.models import Demand, Notification, User
from app.models.enums import NotificationKind, UserRole
from tests.conftest import SUPERADMIN_TG_ID, auth, guest, in_days, member
from tests.test_audience import approved_event


async def test_admin_sees_event_hidden_by_audience(client, session):
    """Встреча «только для бакалавров» видна оргкомитету в списке — иначе
    администратор, сам ограничивший аудиторию, её бы и потерял."""
    event_id = await approved_event(client, session, audience=["bachelor"])
    admin = await member(client, SUPERADMIN_TG_ID, "Оргкомитет")

    listing = await client.get("/api/admin/events", headers=auth(admin))

    assert listing.status_code == 200, listing.text
    row = next(item for item in listing.json() if item["id"] == event_id)
    assert row["status"] == "voting"
    assert row["organizer_name"] == "Ведущий"
    assert row["audience"] == ["bachelor"]


async def test_admin_manages_any_event(client, session):
    event_id = await approved_event(client, session, audience=[])
    admin = await member(client, SUPERADMIN_TG_ID, "Оргкомитет")
    outsider = await guest(client, 3005, "Гость")

    as_admin = (await client.get(f"/api/events/{event_id}", headers=auth(admin))).json()
    as_guest = (await client.get(f"/api/events/{event_id}", headers=auth(outsider))).json()

    assert as_admin["can_manage"] and as_admin["is_admin"]
    assert not as_guest["can_manage"] and not as_guest["is_admin"]


async def test_cancel_notifies_and_returns_demand(client, session):
    event_id = await approved_event(client, session, audience=[])
    admin = await member(client, SUPERADMIN_TG_ID, "Оргкомитет")
    reader = await member(client, 3006, "Читатель")
    event = (await client.get(f"/api/events/{event_id}", headers=auth(reader))).json()
    await client.post(
        f"/api/books/{event['book']['id']}/demand", json={"event_type_ids": []},
        headers=auth(reader),
    )
    await client.post(
        f"/api/events/{event_id}/vote",
        json={"slot_ids": [event["slots"][0]["id"]]},
        headers=auth(reader),
    )
    await client.post(
        f"/api/events/{event_id}/decide",
        json={"slot_id": event["slots"][0]["id"]},
        headers=auth(admin),
    )

    cancelled = await client.post(
        f"/api/events/{event_id}/cancel", json={"reason": "Ведущий заболел"}, headers=auth(admin)
    )

    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["status"] == "cancelled"
    reader_id = (
        await session.execute(sa.select(User.id).where(User.tg_id == 3006))
    ).scalar_one()
    kinds = (
        await session.execute(
            sa.select(Notification.kind).where(Notification.user_id == reader_id)
        )
    ).scalars().all()
    assert NotificationKind.EVENT_CANCELLED in kinds
    # Назначение закрыло спрос; отмена его возвращает.
    alive = (
        await session.execute(
            sa.select(sa.func.count()).where(
                Demand.user_id == reader_id, Demand.revoked_at.is_(None)
            )
        )
    ).scalar_one()
    assert alive == 1

    again = await client.post(
        f"/api/events/{event_id}/cancel", json={"reason": "Ещё раз"}, headers=auth(admin)
    )
    assert again.status_code == 409


async def test_admin_publishes_slots_for_organizer(client, session):
    """Ведущий прислал окна в форум, а не в приложение — администратор
    расставляет их за него."""
    admin = await member(client, SUPERADMIN_TG_ID, "Оргкомитет")
    event_id = await approved_event(client, session, audience=[])
    listing = (await client.get("/api/admin/events", headers=auth(admin))).json()
    assert any(item["id"] == event_id for item in listing)

    # approved_event уже опубликовал окна; второй раз — конфликт, а не 403.
    again = await client.post(
        f"/api/events/{event_id}/slots",
        json={"slots": [{"starts_at": in_days(30)}]},
        headers=auth(admin),
    )
    assert again.status_code == 409


async def test_moderator_has_no_access_to_events(client, session):
    moderator = await member(client, 3007, "Модератор")
    await session.execute(
        sa.update(User).where(User.tg_id == 3007).values(role=UserRole.MODERATOR)
    )
    await session.commit()

    assert (await client.get("/api/admin/events", headers=auth(moderator))).status_code == 403
    books = await client.get("/api/admin/book-requests", headers=auth(moderator))
    assert books.status_code == 200

