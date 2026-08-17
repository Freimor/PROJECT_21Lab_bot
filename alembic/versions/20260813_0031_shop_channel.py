"""Store Telegram shop-card coordinates on products.

Revision ID: 20260813_0031
Revises: 20260812_0030
Create Date: 2026-08-13
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260813_0031"
down_revision: str | None = "20260812_0030"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("products", sa.Column("shop_message_id", sa.BigInteger(), nullable=True))
    op.add_column("products", sa.Column("shop_chat_id", sa.BigInteger(), nullable=True))
    op.add_column("products", sa.Column("shop_file_id", sa.String(length=255), nullable=True))
    op.create_index(
        "ix_products_shop_chat_message",
        "products",
        ["shop_chat_id", "shop_message_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_products_shop_chat_message", table_name="products")
    op.drop_column("products", "shop_file_id")
    op.drop_column("products", "shop_chat_id")
    op.drop_column("products", "shop_message_id")
