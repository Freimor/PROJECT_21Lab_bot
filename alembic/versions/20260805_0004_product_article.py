"""Add unique product article (SKU).

Revision ID: 20260805_0004
Revises: 20260805_0003
Create Date: 2026-08-05
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260805_0004"
down_revision: str | None = "20260805_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("products", sa.Column("article", sa.String(length=64), nullable=True))
    op.execute(sa.text("UPDATE products SET article = 'ART-' || id::text WHERE article IS NULL"))
    op.alter_column("products", "article", nullable=False)
    op.create_unique_constraint("uq_products_article", "products", ["article"])


def downgrade() -> None:
    op.drop_constraint("uq_products_article", "products", type_="unique")
    op.drop_column("products", "article")
