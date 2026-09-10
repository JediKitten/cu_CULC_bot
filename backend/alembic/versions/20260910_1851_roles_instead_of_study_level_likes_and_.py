"""roles instead of study level, likes and favourites

Ступень обучения переехала в саму роль: «бакалавр» и «магистрант» — это разные
ответы на один вопрос, а двумя колонками они позволяли состояния вроде
«сотрудник-магистрант». Направление и курс убраны: их больше не спрашивают.

CHECK-ограничения приходится пересобирать руками — autogenerate их не
сравнивает, и без этого база отвергала бы новые значения ролей.

Revision ID: 7d6674527ccd
Revises: 1efa509c3770
Create Date: 2026-09-10 18:51:33.221864+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = '7d6674527ccd'
down_revision: str | None = '1efa509c3770'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Роли: «студент» разделился на бакалавра и магистранта, «гость» остался.
MEMBER_KINDS = ("applicant", "bachelor", "master", "staff", "guest")
READING_PACES = ("none", "rare", "steady", "fast")
PARTICIPATION_STATES = ("going", "declined", "waitlist")


def _recheck(table: str, column: str, name: str, values: tuple[str, ...]) -> None:
    """Пересобирает CHECK со списком допустимых значений."""
    allowed = ", ".join(f"'{v}'" for v in values)
    op.execute(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS ck_{table}_{name}")
    op.create_check_constraint(name, table, sa.text(f"{column} IN ({allowed})"))


def upgrade() -> None:
    op.add_column("profiles", sa.Column("preferences_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "profiles",
        sa.Column("reminder_dismissed", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )
    op.add_column("profiles", sa.Column("reminder_hidden_at", sa.DateTime(timezone=True), nullable=True))

    # Сначала переносим данные, потом рушим колонку, из которой их берём.
    # Старое «student» без ступени считаем бакалавром: так записаны почти все,
    # а магистранта человек поправит сам — роль видна в профиле.
    op.execute("ALTER TABLE profiles DROP CONSTRAINT IF EXISTS ck_profiles_member_kind")
    op.execute(
        """
        UPDATE profiles
           SET member_kind = CASE
                 WHEN member_kind <> 'student' THEN member_kind
                 WHEN study_level = 'master' THEN 'master'
                 ELSE 'bachelor'
               END
        """
    )
    _recheck("profiles", "member_kind", "member_kind", MEMBER_KINDS)

    # Кто уже отвечал про вкусы — того не дёргаем напоминанием заново.
    op.execute(
        """
        UPDATE profiles
           SET preferences_at = completed_at
         WHERE completed_at IS NOT NULL
           AND (reading_pace IS NOT NULL OR club_experience IS NOT NULL
                OR cardinality(genres) > 0)
        """
    )

    op.drop_column("profiles", "study_level")
    op.drop_column("profiles", "program")
    op.drop_column("profiles", "year")

    _recheck("profiles", "reading_pace", "reading_pace", READING_PACES)

    # «Может быть» больше нет: оно не отвечало на вопрос, на сколько человек
    # рассчитывать. Такие записи убираем — решение просто не принято.
    op.execute("DELETE FROM participations WHERE state = 'maybe'")
    _recheck("participations", "state", "participation_state", PARTICIPATION_STATES)

    op.add_column(
        "reading_entries",
        sa.Column("liked", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )
    op.add_column("reading_entries", sa.Column("favourite_position", sa.Integer(), nullable=True))
    op.create_check_constraint(
        "favourite_position_range",
        "reading_entries",
        sa.text("favourite_position IS NULL OR favourite_position BETWEEN 1 AND 4"),
    )
    op.create_index(
        "uq_favourite_slot",
        "reading_entries",
        ["user_id", "favourite_position"],
        unique=True,
        postgresql_where=sa.text("favourite_position IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_favourite_slot",
        table_name="reading_entries",
        postgresql_where=sa.text("favourite_position IS NOT NULL"),
    )
    op.drop_constraint("ck_reading_entries_favourite_position_range", "reading_entries")
    op.drop_column("reading_entries", "favourite_position")
    op.drop_column("reading_entries", "liked")

    op.add_column("profiles", sa.Column("year", sa.INTEGER(), nullable=True))
    op.add_column("profiles", sa.Column("program", sa.VARCHAR(length=32), nullable=True))
    op.add_column("profiles", sa.Column("study_level", sa.VARCHAR(length=32), nullable=True))
    op.execute(
        "UPDATE profiles SET study_level = member_kind, member_kind = 'student' "
        "WHERE member_kind IN ('bachelor', 'master')"
    )
    _recheck("profiles", "member_kind", "member_kind", ("student", "applicant", "staff", "guest"))
    _recheck("profiles", "reading_pace", "reading_pace", ("rare", "steady", "fast"))
    _recheck(
        "participations", "state", "participation_state", ("going", "maybe", "declined", "waitlist")
    )

    op.drop_column("profiles", "reminder_hidden_at")
    op.drop_column("profiles", "reminder_dismissed")
    op.drop_column("profiles", "preferences_at")
