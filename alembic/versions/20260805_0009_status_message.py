"""Add status_message_id for home status card.

Revision ID: 20260805_0009
Revises: 20260805_0008
Create Date: 2026-08-05
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260805_0009"
down_revision: str | None = "20260805_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("status_message_id", sa.BigInteger(), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "status_message_id")
