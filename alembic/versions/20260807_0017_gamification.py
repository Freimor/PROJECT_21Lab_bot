"""Gamification: ritual, blessings, quests, seasons, meme collections.

Revision ID: 20260807_0017
Revises: 20260806_0016
Create Date: 2026-08-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260807_0017"
down_revision: str | None = "20260806_0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("ritual_streak", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column("users", sa.Column("ritual_last_at", sa.Date(), nullable=True))

    op.add_column(
        "content_templates",
        sa.Column(
            "collection_key",
            sa.String(length=64),
            nullable=False,
            server_default="default",
        ),
    )

    op.create_table(
        "blessings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("from_id", sa.BigInteger(), sa.ForeignKey("users.telegram_id"), nullable=False),
        sa.Column("to_id", sa.BigInteger(), sa.ForeignKey("users.telegram_id"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("ix_blessings_from_created", "blessings", ["from_id", "created_at"])

    op.create_table(
        "community_quests",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("media", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("skill_ids", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("required_participants", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("grace_reward", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("respect_reward", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="open"),
        sa.Column("chat_id", sa.BigInteger(), nullable=True),
        sa.Column("message_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "created_by", sa.BigInteger(), sa.ForeignKey("users.telegram_id"), nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("quest_date", sa.Date(), nullable=True),
        sa.UniqueConstraint("number", name="uq_community_quests_number"),
    )
    op.create_index("ix_community_quests_status", "community_quests", ["status"])
    op.create_index(
        "ix_community_quests_chat_message", "community_quests", ["chat_id", "message_id"]
    )

    op.create_table(
        "community_quest_members",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "quest_id",
            sa.Integer(),
            sa.ForeignKey("community_quests.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.telegram_id"), nullable=False),
        sa.Column(
            "joined_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("reward_grace", sa.Integer(), nullable=True),
        sa.Column("reward_respect", sa.Integer(), nullable=True),
        sa.UniqueConstraint("quest_id", "user_id", name="uq_quest_member"),
    )

    op.create_table(
        "season_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("starts_on", sa.Date(), nullable=False),
        sa.Column("ends_on", sa.Date(), nullable=False),
        sa.Column(
            "meme_collection", sa.String(length=64), nullable=False, server_default="default"
        ),
        sa.Column("phrases_key", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("start_announced", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("end_announced", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("reminder_sent", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint("code", name="uq_season_events_code"),
    )


def downgrade() -> None:
    op.drop_table("season_events")
    op.drop_table("community_quest_members")
    op.drop_index("ix_community_quests_chat_message", table_name="community_quests")
    op.drop_index("ix_community_quests_status", table_name="community_quests")
    op.drop_table("community_quests")
    op.drop_index("ix_blessings_from_created", table_name="blessings")
    op.drop_table("blessings")
    op.drop_column("content_templates", "collection_key")
    op.drop_column("users", "ritual_last_at")
    op.drop_column("users", "ritual_streak")
