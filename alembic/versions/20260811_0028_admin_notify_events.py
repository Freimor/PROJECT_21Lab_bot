"""Admin browser notification event feed.

Revision ID: 20260811_0028
Revises: 20260808_0027
Create Date: 2026-08-11
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260811_0028"
down_revision: str | None = "20260808_0027"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "admin_notify_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("event_type", sa.String(length=40), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("body", sa.Text(), nullable=False, server_default=""),
        sa.Column("link", sa.String(length=300), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_admin_notify_events_created",
        "admin_notify_events",
        ["created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_admin_notify_events_created", table_name="admin_notify_events")
    op.drop_table("admin_notify_events")
