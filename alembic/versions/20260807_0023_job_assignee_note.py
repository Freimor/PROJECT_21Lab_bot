"""Private note for service job assignee.

Revision ID: 20260807_0023
Revises: 20260807_0022
Create Date: 2026-08-07
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260807_0023"
down_revision: str | None = "20260807_0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "service_jobs",
        sa.Column("assignee_note", sa.Text(), nullable=False, server_default=""),
    )


def downgrade() -> None:
    op.drop_column("service_jobs", "assignee_note")
