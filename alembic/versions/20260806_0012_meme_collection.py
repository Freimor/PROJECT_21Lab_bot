"""Meme collection metadata and approved meme counter.

Revision ID: 20260806_0012
Revises: 20260805_0011
Create Date: 2026-08-06
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260806_0012"
down_revision: str | None = "20260805_0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("approved_meme_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "content_templates",
        sa.Column("title", sa.String(length=160), nullable=False, server_default="Мем"),
    )
    op.add_column(
        "content_templates",
        sa.Column("author_id", sa.BigInteger(), sa.ForeignKey("users.telegram_id"), nullable=True),
    )
    op.add_column(
        "content_templates",
        sa.Column("reaction_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "content_items",
        sa.Column(
            "template_id",
            sa.Integer(),
            sa.ForeignKey("content_templates.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("ix_content_items_template_id", "content_items", ["template_id"])
    op.create_index(
        "ix_content_templates_kind_active",
        "content_templates",
        ["kind", "is_active"],
    )


def downgrade() -> None:
    op.drop_index("ix_content_templates_kind_active", table_name="content_templates")
    op.drop_index("ix_content_items_template_id", table_name="content_items")
    op.drop_column("content_items", "template_id")
    op.drop_column("content_templates", "reaction_count")
    op.drop_column("content_templates", "author_id")
    op.drop_column("content_templates", "title")
    op.drop_column("users", "approved_meme_count")
