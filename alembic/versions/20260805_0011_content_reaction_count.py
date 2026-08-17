"""Track reaction totals on published content for respect.

Revision ID: 20260805_0011
Revises: 20260805_0010
Create Date: 2026-08-05
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260805_0011"
down_revision: str | None = "20260805_0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "content_items",
        sa.Column("reaction_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_index(
        "ix_content_published_chat_message",
        "content_items",
        ["published_channel_id", "published_message_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_content_published_chat_message", table_name="content_items")
    op.drop_column("content_items", "reaction_count")
