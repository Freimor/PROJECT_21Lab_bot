"""Multi-skill jobs, prices, and respect rewards.

Revision ID: 20260806_0016
Revises: 20260806_0015
Create Date: 2026-08-06
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260806_0016"
down_revision: str | None = "20260806_0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "products",
        sa.Column("skill_ids", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
    )
    op.add_column("products", sa.Column("respect_reward", sa.Integer(), nullable=True))
    op.execute(
        sa.text(
            """
            UPDATE products
            SET skill_ids = CASE
                WHEN skill_id IS NULL OR skill_id = '' THEN '[]'::json
                ELSE json_build_array(skill_id)
            END
            """
        )
    )
    op.drop_column("products", "skill_id")

    op.add_column(
        "service_jobs",
        sa.Column("skill_ids", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
    )
    op.add_column(
        "service_jobs",
        sa.Column("price", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "service_jobs",
        sa.Column("respect_reward", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "service_jobs",
        sa.Column("reserved", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.execute(
        sa.text(
            """
            UPDATE service_jobs
            SET skill_ids = CASE
                WHEN skill_id IS NULL OR skill_id = '' THEN '[]'::json
                ELSE json_build_array(skill_id)
            END
            """
        )
    )
    op.drop_column("service_jobs", "skill_id")


def downgrade() -> None:
    op.add_column(
        "service_jobs",
        sa.Column("skill_id", sa.String(length=64), nullable=True),
    )
    op.execute(
        sa.text(
            """
            UPDATE service_jobs
            SET skill_id = COALESCE(skill_ids->>0, '')
            """
        )
    )
    op.alter_column("service_jobs", "skill_id", nullable=False)
    op.drop_column("service_jobs", "reserved")
    op.drop_column("service_jobs", "respect_reward")
    op.drop_column("service_jobs", "price")
    op.drop_column("service_jobs", "skill_ids")

    op.add_column(
        "products",
        sa.Column("skill_id", sa.String(length=64), nullable=True),
    )
    op.execute(
        sa.text(
            """
            UPDATE products
            SET skill_id = skill_ids->>0
            """
        )
    )
    op.drop_column("products", "respect_reward")
    op.drop_column("products", "skill_ids")
