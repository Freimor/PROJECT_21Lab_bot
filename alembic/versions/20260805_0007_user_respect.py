"""Add user respect counter.

Revision ID: 20260805_0007
Revises: 20260805_0006
Create Date: 2026-08-05
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260805_0007"
down_revision: str | None = "20260805_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("respect", sa.Integer(), nullable=False, server_default="0"),
    )
    op.execute(sa.text("UPDATE users SET respect = 0 WHERE staff_role IS NOT NULL"))


def downgrade() -> None:
    op.drop_column("users", "respect")
