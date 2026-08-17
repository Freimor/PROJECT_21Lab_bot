"""Add feedback_reports for /bug and /upgrade intake.

Revision ID: 20260811_0029
Revises: 20260811_0028
Create Date: 2026-08-11
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260811_0029"
down_revision: str | None = "20260811_0028"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "feedback_reports",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("author_id", sa.BigInteger(), sa.ForeignKey("users.telegram_id"), nullable=True),
        sa.Column("author_name", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("author_username", sa.String(length=100), nullable=True),
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column("message_id", sa.BigInteger(), nullable=False),
        sa.Column("message_thread_id", sa.BigInteger(), nullable=True),
        sa.Column("text", sa.Text(), nullable=False, server_default=""),
        sa.Column("media", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")),
        sa.Column("decided_by", sa.BigInteger(), sa.ForeignKey("users.telegram_id"), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decision_note", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint("chat_id", "message_id", name="uq_feedback_chat_message"),
    )
    op.create_index(
        "ix_feedback_reports_status_kind",
        "feedback_reports",
        ["status", "kind"],
    )


def downgrade() -> None:
    op.drop_index("ix_feedback_reports_status_kind", table_name="feedback_reports")
    op.drop_table("feedback_reports")
