"""Job result review fields and REVIEW status.

Revision ID: 20260807_0024
Revises: 20260807_0023
Create Date: 2026-08-07
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260807_0024"
down_revision: str | None = "20260807_0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "service_jobs",
        sa.Column("result_text", sa.Text(), nullable=False, server_default=""),
    )
    op.add_column(
        "service_jobs",
        sa.Column("result_media", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
    )
    op.add_column(
        "service_jobs",
        sa.Column("content_item_id", sa.Integer(), sa.ForeignKey("content_items.id"), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("service_jobs", "content_item_id")
    op.drop_column("service_jobs", "result_media")
    op.drop_column("service_jobs", "result_text")
