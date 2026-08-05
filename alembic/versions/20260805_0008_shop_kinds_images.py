"""Shop product kinds and image path.

Revision ID: 20260805_0008
Revises: 20260805_0007
Create Date: 2026-08-05
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260805_0008"
down_revision: str | None = "20260805_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("products", sa.Column("image_path", sa.String(length=255), nullable=True))
    op.execute(sa.text("UPDATE products SET kind = 'merch' WHERE kind = 'physical'"))
    op.execute(sa.text("UPDATE products SET kind = 'service' WHERE kind = 'rank'"))
    op.execute(
        sa.text("UPDATE products SET kind = 'device' WHERE kind NOT IN ('merch', 'service', 'device')")
    )


def downgrade() -> None:
    op.execute(sa.text("UPDATE products SET kind = 'physical' WHERE kind = 'merch'"))
    op.execute(sa.text("UPDATE products SET kind = 'physical' WHERE kind = 'device'"))
    op.drop_column("products", "image_path")
