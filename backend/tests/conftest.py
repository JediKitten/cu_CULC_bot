"""Тесты идут в отдельной базе litclub_test — прогон не должен трогать рабочие данные.

Движок создаётся на каждый тест: соединение asyncpg привязано к event loop,
а pytest-asyncio даёт каждому тесту свой. Схема разворачивается один раз.
"""

import hashlib
import hmac
import json
import time
from collections.abc import AsyncIterator
from urllib.parse import urlencode

import pytest
import sqlalchemy as sa
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_config
from app.models import Base, EventType
from app.models.enums import EventTypeStatus

TEST_DB = "litclub_test"
_schema_ready = False

BOT_TOKEN = "123456:TEST-TOKEN-FOR-SIGNATURE-CHECKS"
SUPERADMIN_TG_ID = 777001

# Те же форматы, что засевает миграция, — тестам нужны хотя бы два.
SEED_TYPES = (
    ("balagan", "Балаган", True),
    ("regular", "Regular", True),
    ("round_table", "Круглый стол знатоков", False),
)


def _url(database: str) -> str:
    return get_config().database_url.rsplit("/", 1)[0] + f"/{database}"


async def _ensure_schema() -> None:
    global _schema_ready
    if _schema_ready:
        return

    admin = create_async_engine(_url("postgres"), isolation_level="AUTOCOMMIT")
    async with admin.connect() as conn:
        exists = await conn.scalar(
            sa.text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": TEST_DB}
        )
        if not exists:
            await conn.execute(sa.text(f'CREATE DATABASE "{TEST_DB}"'))
    await admin.dispose()

    engine = create_async_engine(_url(TEST_DB))
    async with engine.begin() as conn:
        await conn.execute(sa.text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    await engine.dispose()
    _schema_ready = True


@pytest.fixture
async def session() -> AsyncIterator[AsyncSession]:
    await _ensure_schema()
    engine = create_async_engine(_url(TEST_DB))
    maker = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async with maker() as session:
        for slug, title, requires_reading in SEED_TYPES:
            session.add(
                EventType(
                    slug=slug,
                    title=title,
                    requires_reading=requires_reading,
                    is_builtin=True,
                    status=EventTypeStatus.ACTIVE,
                )
            )
        await session.commit()

        yield session

        await session.rollback()
        # Каждый тест начинает с чистых таблиц: счётчики спроса считаются по
        # всей базе, и остатки соседнего теста молча исказили бы результат.
        tables = ", ".join(f'"{t.name}"' for t in Base.metadata.sorted_tables)
        await session.execute(sa.text(f"TRUNCATE TABLE {tables} CASCADE"))
        await session.commit()

    await engine.dispose()


def make_init_data(tg_id: int, first_name: str, token: str = BOT_TOKEN) -> str:
    """Подписываем initData ровно так же, как это делает Telegram."""
    fields = {
        "auth_date": str(int(time.time())),
        "query_id": "AAF_test",
        "user": json.dumps(
            {"id": tg_id, "first_name": first_name, "username": f"u{tg_id}"},
            separators=(",", ":"),
        ),
    }
    check_string = "\n".join(f"{k}={fields[k]}" for k in sorted(fields))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    fields["hash"] = hmac.new(secret, check_string.encode(), hashlib.sha256).hexdigest()
    return urlencode(fields)


@pytest.fixture
async def client(session, monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", BOT_TOKEN)
    monkeypatch.setenv("BOOTSTRAP_SUPERADMIN_TG_ID", str(SUPERADMIN_TG_ID))
    get_config.cache_clear()

    from app.db import get_session
    from app.main import app

    app.dependency_overrides[get_session] = lambda: session
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client
    app.dependency_overrides.clear()
    get_config.cache_clear()


async def login(client, tg_id: int, name: str) -> str:
    """Вход без анкеты. Возвращает токен."""
    response = await client.post(
        "/api/auth/telegram", json={"init_data": make_init_data(tg_id, name)}
    )
    assert response.status_code == 200, response.text
    return response.json()["token"]


# Почта ЦУ: единственный домен, который принимает анкета.
CU_EMAIL = "student@edu.centraluniversity.ru"


async def onboard(
    client,
    token: str,
    *,
    member_kind: str = "student",
    email: str | None = CU_EMAIL,
    full_name: str = "Тестовый Участник",
    study_level: str | None = "bachelor",
    program: str | None = "development",
    year: int | None = 2,
) -> dict:
    response = await client.put(
        "/api/profile",
        json={
            "member_kind": member_kind,
            "full_name": full_name,
            "study_level": study_level,
            "program": program,
            "year": year,
            "university_email": email,
            "reading_pace": "steady",
            "club_experience": "visitor",
            "genres": ["Классика"],
            "event_type_ids": [],
        },
        headers=auth(token),
    )
    assert response.status_code == 200, response.text
    return response.json()


async def member(client, tg_id: int, name: str, **kwargs) -> str:
    """Вошедший участник с заполненной анкетой — то, с чего начинается
    большинство сценариев."""
    token = await login(client, tg_id, name)
    await onboard(client, token, full_name=name, **kwargs)
    return token


async def guest(client, tg_id: int, name: str) -> str:
    """Внешний гость: ни почты, ни ступени, ни курса."""
    return await member(
        client,
        tg_id,
        name,
        member_kind="guest",
        email=None,
        study_level=None,
        program=None,
        year=None,
    )


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}
