"""Add avatar_file_id to users.

Revision ID: 20260805_0002
Revises: 20260804_0001
Create Date: 2026-08-05
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260805_0002"
down_revision: str | None = "20260804_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("avatar_file_id", sa.String(length=255), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "avatar_file_id")
