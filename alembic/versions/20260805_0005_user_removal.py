"""Add user removal fields.

Revision ID: 20260805_0005
Revises: 20260805_0004
Create Date: 2026-08-05
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260805_0005"
down_revision: str | None = "20260805_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("removal_reason", sa.String(length=32), nullable=True))
    op.add_column("users", sa.Column("removed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "users",
        sa.Column("removed_by", sa.BigInteger(), sa.ForeignKey("users.telegram_id"), nullable=True),
    )
    op.execute(sa.text("UPDATE users SET balance = 0 WHERE staff_role IS NOT NULL"))


def downgrade() -> None:
    op.drop_column("users", "removed_by")
    op.drop_column("users", "removed_at")
    op.drop_column("users", "removal_reason")
