"""Staff flag for switching the miniapp to a test participant.

Revision ID: 20261001_0036
Revises: 20261001_0035
Create Date: 2026-10-01
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20261001_0036"
down_revision: str | None = "20261001_0035"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("can_use_testuser", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "users",
        sa.Column("testuser_active", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("users", "testuser_active")
    op.drop_column("users", "can_use_testuser")
