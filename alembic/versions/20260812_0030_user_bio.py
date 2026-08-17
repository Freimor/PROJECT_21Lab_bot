"""Add users.bio for public profile cards.

Revision ID: 20260812_0030
Revises: 20260811_0029
Create Date: 2026-08-12
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260812_0030"
down_revision: str | None = "20260811_0029"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("bio", sa.Text(), nullable=True))
    op.execute(
        """
        UPDATE users AS u
        SET bio = a.bio
        FROM (
            SELECT DISTINCT ON (user_id) user_id, bio
            FROM join_applications
            WHERE status = 'approved'
              AND bio IS NOT NULL
              AND btrim(bio) <> ''
            ORDER BY user_id, decided_at DESC NULLS LAST, id DESC
        ) AS a
        WHERE u.telegram_id = a.user_id
          AND (u.bio IS NULL OR btrim(u.bio) = '')
        """
    )


def downgrade() -> None:
    op.drop_column("users", "bio")
