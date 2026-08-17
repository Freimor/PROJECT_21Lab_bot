"""Add media JSON to content_templates for meme photos.

Revision ID: 20260806_0013
Revises: 20260806_0012
Create Date: 2026-08-06
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260806_0013"
down_revision: str | None = "20260806_0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "content_templates",
        sa.Column("media", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
    )
    # Backfill from approved meme applications that already point at a template.
    op.execute(
        """
        UPDATE content_templates AS t
        SET media = c.media
        FROM content_items AS c
        WHERE c.template_id = t.id
          AND c.kind = 'meme'
          AND c.media IS NOT NULL
          AND c.media::text NOT IN ('[]', 'null')
        """
    )


def downgrade() -> None:
    op.drop_column("content_templates", "media")
