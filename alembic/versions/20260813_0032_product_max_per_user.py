"""Per-user purchase cap for shop products.

Revision ID: 20260813_0032
Revises: 20260813_0031
Create Date: 2026-08-13
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260813_0032"
down_revision: str | None = "20260813_0031"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "products",
        sa.Column("max_per_user", sa.Integer(), nullable=True, server_default="2"),
    )
    op.alter_column("products", "max_per_user", server_default=None)


def downgrade() -> None:
    op.drop_column("products", "max_per_user")
