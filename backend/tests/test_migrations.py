"""Миграции на пустой базе.

Отдельный тест понадобился после того, как боевая выкладка легла: схема
требовала расширение pg_trgm, которое на рабочей машине оказалось заведено
руками при первой настройке, а в свежей базе его не было. Остальные тесты
этого не ловили — они разворачивают схему через metadata.create_all, а не
миграциями, да ещё и создают расширение сами.

Здесь всё наоборот: чистая база, ничего заранее не создано, alembic проходит
свой путь целиком — ровно как при первом запуске в проде.
"""

import subprocess
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import get_config
from app.models import Base

SCRATCH_DB = "litclub_migrations"
BACKEND = Path(__file__).resolve().parent.parent


def _url(database: str) -> str:
    return get_config().database_url.rsplit("/", 1)[0] + f"/{database}"


def _sync_url(database: str) -> str:
    return _url(database).replace("+asyncpg", "")


@pytest.fixture
async def scratch_db():
    admin = create_async_engine(_url("postgres"), isolation_level="AUTOCOMMIT")
    async with admin.connect() as conn:
        await conn.execute(sa.text(f'DROP DATABASE IF EXISTS "{SCRATCH_DB}"'))
        await conn.execute(sa.text(f'CREATE DATABASE "{SCRATCH_DB}"'))
    await admin.dispose()

    yield SCRATCH_DB

    admin = create_async_engine(_url("postgres"), isolation_level="AUTOCOMMIT")
    async with admin.connect() as conn:
        await conn.execute(sa.text(f'DROP DATABASE IF EXISTS "{SCRATCH_DB}"'))
    await admin.dispose()


async def test_upgrade_head_on_empty_database(scratch_db):
    """alembic upgrade head должен пройти на базе, где нет вообще ничего."""
    result = subprocess.run(
        [str(BACKEND / "venv" / "bin" / "alembic"), "upgrade", "head"],
        cwd=BACKEND,
        env={"PATH": "/usr/bin:/bin", "DATABASE_URL": _url(scratch_db)},
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr[-2000:]

    engine = create_async_engine(_url(scratch_db))
    async with engine.connect() as conn:
        tables = set(
            (
                await conn.execute(
                    sa.text(
                        "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
                    )
                )
            )
            .scalars()
            .all()
        )
        # Схема развернулась целиком, а не наполовину.
        assert set(Base.metadata.tables) <= tables

        # Индекс по названию книги на месте: именно он требовал расширения.
        index = await conn.execute(
            sa.text("SELECT indexdef FROM pg_indexes WHERE indexname = 'ix_books_title_trgm'")
        )
        assert "gin_trgm_ops" in (index.scalar_one_or_none() or "")

        # Справочник форматов засеян второй миграцией.
        seeded = await conn.execute(sa.text("SELECT count(*) FROM event_types"))
        assert seeded.scalar_one() == 7
    await engine.dispose()
