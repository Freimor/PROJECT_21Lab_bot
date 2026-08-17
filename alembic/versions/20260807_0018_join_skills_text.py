"""Free-text skills on join applications.

Revision ID: 20260807_0018
Revises: 20260807_0017
Create Date: 2026-08-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260807_0018"
down_revision: str | None = "20260807_0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {col["name"] for col in inspector.get_columns("join_applications")}
    if "skills_text" not in columns:
        op.add_column("join_applications", sa.Column("skills_text", sa.Text(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {col["name"] for col in inspector.get_columns("join_applications")}
    if "skills_text" in columns:
        op.drop_column("join_applications", "skills_text")
