"""Editable start/end announcement texts for seasons.

Revision ID: 20260814_0033
Revises: 20260813_0032
Create Date: 2026-08-14
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260814_0033"
down_revision: str | None = "20260813_0032"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "season_events",
        sa.Column("start_message", sa.Text(), nullable=False, server_default=""),
    )
    op.add_column(
        "season_events",
        sa.Column("end_message", sa.Text(), nullable=False, server_default=""),
    )
    op.alter_column("season_events", "start_message", server_default=None)
    op.alter_column("season_events", "end_message", server_default=None)


def downgrade() -> None:
    op.drop_column("season_events", "end_message")
    op.drop_column("season_events", "start_message")
