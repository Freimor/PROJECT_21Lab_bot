"""Skills, jobs thread, and service job tables.

Revision ID: 20260806_0015
Revises: 20260806_0014
Create Date: 2026-08-06
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260806_0015"
down_revision: str | None = "20260806_0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("skill_ids", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
    )
    op.add_column(
        "users",
        sa.Column(
            "job_notify_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column("join_applications", sa.Column("bio", sa.Text(), nullable=True))
    op.add_column(
        "join_applications",
        sa.Column("skill_ids", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
    )
    op.add_column(
        "products",
        sa.Column("skill_id", sa.String(length=64), nullable=True),
    )
    op.create_table(
        "service_jobs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("customer_id", sa.BigInteger(), sa.ForeignKey("users.telegram_id"), nullable=False),
        sa.Column("skill_id", sa.String(length=64), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("media", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id"), nullable=True),
        sa.Column("order_id", sa.Integer(), sa.ForeignKey("orders.id"), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="open"),
        sa.Column("assignee_id", sa.BigInteger(), sa.ForeignKey("users.telegram_id"), nullable=True),
        sa.Column("job_message_id", sa.BigInteger(), nullable=True),
        sa.Column("job_chat_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_service_jobs_status", "service_jobs", ["status"])
    op.create_index(
        "ix_service_jobs_chat_message",
        "service_jobs",
        ["job_chat_id", "job_message_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_service_jobs_chat_message", table_name="service_jobs")
    op.drop_index("ix_service_jobs_status", table_name="service_jobs")
    op.drop_table("service_jobs")
    op.drop_column("products", "skill_id")
    op.drop_column("join_applications", "skill_ids")
    op.drop_column("join_applications", "bio")
    op.drop_column("users", "job_notify_enabled")
    op.drop_column("users", "skill_ids")
