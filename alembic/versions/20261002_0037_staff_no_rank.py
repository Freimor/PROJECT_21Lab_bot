"""Staff have a role and no community rank.

Revision ID: 20261002_0037
Revises: 20261001_0036
Create Date: 2026-10-02
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20261002_0037"
down_revision: str | None = "20261001_0036"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column("users", "rank", existing_type=sa.String(length=32), nullable=True)
    op.execute(sa.text("UPDATE users SET rank = NULL WHERE staff_role IS NOT NULL"))


def downgrade() -> None:
    op.execute(sa.text("UPDATE users SET rank = 'novice' WHERE rank IS NULL"))
    op.alter_column("users", "rank", existing_type=sa.String(length=32), nullable=False)
