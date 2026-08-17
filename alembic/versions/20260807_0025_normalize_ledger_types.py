"""Normalize ledger entry_type to StrEnum values (lowercase).

Revision ID: 20260807_0025
Revises: 20260807_0024
Create Date: 2026-08-07
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260807_0025"
down_revision: str | None = "20260807_0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "ledger_entries",
        "entry_type",
        existing_type=sa.String(length=16),
        type_=sa.String(length=32),
        existing_nullable=False,
    )
    op.execute(
        sa.text(
            "UPDATE ledger_entries SET entry_type = lower(entry_type) "
            "WHERE entry_type <> lower(entry_type)"
        )
    )


def downgrade() -> None:
    op.alter_column(
        "ledger_entries",
        "entry_type",
        existing_type=sa.String(length=32),
        type_=sa.String(length=16),
        existing_nullable=False,
    )
