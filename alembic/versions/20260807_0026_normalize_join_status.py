"""Normalize join_applications status/kind to StrEnum values.

Revision ID: 20260807_0026
Revises: 20260807_0025
Create Date: 2026-08-08
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260807_0026"
down_revision: str | None = "20260807_0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "join_applications",
        "status",
        existing_type=sa.String(length=32),
        type_=sa.String(length=32),
        existing_nullable=False,
    )
    op.alter_column(
        "join_applications",
        "kind",
        existing_type=sa.String(length=32),
        type_=sa.String(length=32),
        existing_nullable=False,
    )
    op.execute(
        sa.text(
            "UPDATE join_applications SET status = lower(status) "
            "WHERE status <> lower(status)"
        )
    )
    op.execute(
        sa.text(
            "UPDATE join_applications SET kind = lower(kind) "
            "WHERE kind <> lower(kind)"
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE join_applications SET status = upper(status) "
            "WHERE status = lower(status)"
        )
    )
    op.execute(
        sa.text(
            "UPDATE join_applications SET kind = upper(kind) "
            "WHERE kind = lower(kind)"
        )
    )
