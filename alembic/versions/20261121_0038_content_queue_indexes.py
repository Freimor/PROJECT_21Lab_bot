"""Add content queue / schedule indexes.

Revision ID: 20261121_0038
Revises: 20261002_0037
Create Date: 2026-11-21
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20261121_0038"
down_revision: str | None = "20261002_0037"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "ix_content_status_kind",
        "content_items",
        ["status", "kind"],
    )
    op.create_index(
        "ix_content_scheduled_due",
        "content_items",
        ["status", "scheduled_at"],
        postgresql_where=sa.text("scheduled_at IS NOT NULL"),
        sqlite_where=sa.text("scheduled_at IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_content_scheduled_due", table_name="content_items")
    op.drop_index("ix_content_status_kind", table_name="content_items")
