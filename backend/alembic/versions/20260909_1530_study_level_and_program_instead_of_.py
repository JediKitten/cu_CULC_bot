"""study level and program instead of faculty

Свободный текст «факультет» заменён на два поля из списка: ступень обучения
и направление. Свободный текст разъезжался бы на десяток написаний одного и
того же и ломал разрезы в аналитике, а правила («направление только у
бакалавров», «"не определился" только на первом курсе») по нему выразить
нечем.

Revision ID: 1efa509c3770
Revises: f1d6d6d73d4c
Create Date: 2026-09-09 15:30:14.554370+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "1efa509c3770"
down_revision: str | None = "f1d6d6d73d4c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Две циклические связи (events → event_slots, meeting_rooms →
# organizer_applications) заведены ещё первой миграцией через use_alter.
# Autogenerate видит их заново при каждом прогоне и предлагает создать
# повторно — на существующем ограничении это упало бы. Здесь их нет намеренно.

STUDY_LEVEL = sa.Enum(
    "bachelor",
    "master",
    name="study_level",
    native_enum=False,
    create_constraint=True,
    length=32,
)

PROGRAM = sa.Enum(
    "development",
    "ai",
    "business",
    "design",
    "undecided",
    name="program",
    native_enum=False,
    create_constraint=True,
    length=32,
)


def upgrade() -> None:
    op.add_column("profiles", sa.Column("study_level", STUDY_LEVEL, nullable=True))
    op.add_column("profiles", sa.Column("program", PROGRAM, nullable=True))
    # Переносить нечего: старое значение — произвольная строка, а новое поле
    # выбирается из списка. Кто уже заполнял анкету, укажет направление заново.
    op.drop_column("profiles", "faculty")


def downgrade() -> None:
    op.add_column("profiles", sa.Column("faculty", sa.VARCHAR(length=128), nullable=True))
    op.drop_column("profiles", "program")
    op.drop_column("profiles", "study_level")
