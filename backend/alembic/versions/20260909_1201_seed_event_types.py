"""seed event types

Семь форматов, с которыми клуб работает сегодня. Заводятся миграцией, а не
кодом при старте: это данные клуба, а не константы, — оргкомитет вправе
переименовать формат или спрятать его, и апгрейд не должен возвращать всё назад.

Revision ID: f1d6d6d73d4c
Revises: 4f3d9b8f7f5e
Create Date: 2026-09-09 12:01:38.556715+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f1d6d6d73d4c"
down_revision: str | None = "4f3d9b8f7f5e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


TYPES = [
    (
        "balagan",
        "Балаган",
        "Встреча-обсуждение без подготовки и сильной модерации: пришли, "
        "прочитав книгу, и говорим кто о чём.",
        True,
        10,
    ),
    (
        "regular",
        "Regular",
        "Модерируемая встреча: читают все, ведущий заранее готовит темы и "
        "следит, куда идёт дискуссия.",
        True,
        20,
    ),
    (
        "round_table",
        "Круглый стол знатоков",
        "Лекция с дебатами или поочерёдным разбором частей книги несколькими "
        "ведущими — оффлайн-подкаст. Гостям читать не нужно, ведущие серьёзно "
        "готовятся: раздатка, презентация, маркетинг. Людей ждём больше обычного.",
        False,
        30,
    ),
    (
        "detective",
        "Детективная студия",
        "Расследуем детектив вместе: версии, улики, доска расследования. Ведут "
        "двое — один знает развязку и готовит материал, второй читает наравне "
        "с гостями. Иногда развязку читаем прямо на встрече.",
        True,
        40,
    ),
    (
        "nonfiction",
        "Нон-фикшн",
        "Всё, что не художественная литература.",
        True,
        50,
    ),
    (
        "classics",
        "Классика",
        "Классика, в том числе русская.",
        True,
        60,
    ),
    (
        "handicraft",
        "Мастер-класс и рукоделие",
        "Мастерим что-то, связанное с книгой или с литклубом. Обычно "
        "сопровождается обсуждением, но иногда просто мастерим.",
        False,
        70,
    ),
]


def upgrade() -> None:
    event_types = sa.table(
        "event_types",
        sa.column("slug", sa.String),
        sa.column("title", sa.String),
        sa.column("description", sa.Text),
        sa.column("requires_reading", sa.Boolean),
        sa.column("is_builtin", sa.Boolean),
        sa.column("status", sa.String),
        sa.column("sort_order", sa.Integer),
    )
    op.bulk_insert(
        event_types,
        [
            {
                "slug": slug,
                "title": title,
                "description": description,
                "requires_reading": requires_reading,
                "is_builtin": True,
                "status": "active",
                "sort_order": sort_order,
            }
            for slug, title, description, requires_reading, sort_order in TYPES
        ],
    )


def downgrade() -> None:
    slugs = ", ".join(f"'{slug}'" for slug, *_ in TYPES)
    op.execute(f"DELETE FROM event_types WHERE is_builtin AND slug IN ({slugs})")
