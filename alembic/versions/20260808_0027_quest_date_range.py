"""Add quest_ends_on for date ranges; backfill single-day ends.

Revision ID: 20260808_0027
Revises: 20260807_0026
Create Date: 2026-08-08
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260808_0027"
down_revision: str | None = "20260807_0026"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "community_quests",
        sa.Column("quest_ends_on", sa.Date(), nullable=True),
    )
    op.execute(
        sa.text(
            "UPDATE community_quests "
            "SET quest_ends_on = quest_date "
            "WHERE quest_date IS NOT NULL AND quest_ends_on IS NULL"
        )
    )


def downgrade() -> None:
    op.drop_column("community_quests", "quest_ends_on")
