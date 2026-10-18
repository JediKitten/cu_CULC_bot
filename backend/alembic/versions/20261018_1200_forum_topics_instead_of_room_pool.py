"""forum topics instead of room pool

Переговорки теперь — темы в одном форуме оргкомитета, а не пул отдельных
супергрупп. У заявки появляется своя тема; занятость комнаты и список её
сообщений больше не нужны: тема удаляется целиком вместе с перепиской.

Старые комнаты — обычные группы, а не форумы. Помечаем их ошибкой проверки,
чтобы бот не пытался заводить в них темы, пока оргкомитет не подключит форум.

Revision ID: 3c1b7e5a9d20
Revises: 9f94e344b7bb
Create Date: 2026-10-18 12:00:00+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "3c1b7e5a9d20"
down_revision: str | None = "9f94e344b7bb"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("organizer_applications", sa.Column("topic_id", sa.Integer(), nullable=True))

    op.drop_index(op.f("ix_room_messages_room_id"), table_name="room_messages")
    op.drop_table("room_messages")

    # Ключ объявлен с use_alter и в первой миграции фактически не создался;
    # IF EXISTS — на случай базы, развёрнутой иначе (metadata.create_all).
    op.execute(
        "ALTER TABLE meeting_rooms DROP CONSTRAINT IF EXISTS "
        "fk_meeting_rooms_current_application_id_organizer_applications"
    )
    op.drop_column("meeting_rooms", "current_application_id")

    op.execute(
        "UPDATE meeting_rooms SET status = 'free', "
        "check_error = 'Это обычная группа, а нужен форум с темами — подключите его заново' "
        "WHERE status <> 'disabled'"
    )


def downgrade() -> None:
    op.add_column(
        "meeting_rooms", sa.Column("current_application_id", sa.Integer(), nullable=True)
    )
    op.create_table(
        "room_messages",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("room_id", sa.Integer(), nullable=False),
        sa.Column("message_id", sa.Integer(), nullable=False),
        sa.Column(
            "sent_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["room_id"],
            ["meeting_rooms.id"],
            name=op.f("fk_room_messages_room_id_meeting_rooms"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_room_messages")),
        sa.UniqueConstraint("room_id", "message_id", name="uq_room_message"),
    )
    op.create_index(op.f("ix_room_messages_room_id"), "room_messages", ["room_id"], unique=False)
    op.drop_column("organizer_applications", "topic_id")
