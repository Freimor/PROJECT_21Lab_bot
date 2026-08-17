"""Add llm_processed flag for two-stage post moderation.

Revision ID: 20260806_0014
Revises: 20260806_0013
Create Date: 2026-08-06
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260806_0014"
down_revision: str | None = "20260806_0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "content_items",
        sa.Column("llm_processed", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    # Existing story/important items already in queue with a draft count as processed.
    op.execute(
        """
        UPDATE content_items
        SET llm_processed = true
        WHERE kind IN ('story', 'important')
          AND draft_text IS NOT NULL
          AND draft_text <> ''
          AND draft_text IS DISTINCT FROM source_text
        """
    )


def downgrade() -> None:
    op.drop_column("content_items", "llm_processed")
