"""Add join applications and user approval flag.

Revision ID: 20260805_0003
Revises: 20260805_0002
Create Date: 2026-08-05
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260805_0003"
down_revision: str | None = "20260805_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("is_approved", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.create_table(
        "join_applications",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.telegram_id"), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("decided_by", sa.BigInteger(), sa.ForeignKey("users.telegram_id")),
        sa.Column("decision_note", sa.Text()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("decided_at", sa.DateTime(timezone=True)),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_join_apps_status_kind", "join_applications", ["status", "kind"])
    op.create_index("ix_join_apps_user_status", "join_applications", ["user_id", "status"])
    # New users must be approved via application; existing ones keep access.
    op.execute(sa.text("UPDATE users SET is_approved = true"))
    op.alter_column("users", "is_approved", server_default=sa.false())


def downgrade() -> None:
    op.drop_index("ix_join_apps_user_status", table_name="join_applications")
    op.drop_index("ix_join_apps_status_kind", table_name="join_applications")
    op.drop_table("join_applications")
    op.drop_column("users", "is_approved")
