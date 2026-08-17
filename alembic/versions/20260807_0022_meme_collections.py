"""Registry table for meme collection keys.

Revision ID: 20260807_0022
Revises: 20260807_0021
Create Date: 2026-08-07
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260807_0022"
down_revision: str | None = "20260807_0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "meme_collections",
        sa.Column("key", sa.String(length=64), primary_key=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
    )
    conn = op.get_bind()
    keys: set[str] = {"default"}
    for row in conn.execute(
        sa.text(
            "SELECT DISTINCT collection_key FROM content_templates "
            "WHERE kind = 'meme' AND collection_key IS NOT NULL"
        )
    ):
        key = (row[0] or "").strip()
        if key:
            keys.add(key)
    # Seasons may reference collections that have no templates yet.
    inspector = sa.inspect(conn)
    if "season_events" in inspector.get_table_names():
        for row in conn.execute(
            sa.text(
                "SELECT DISTINCT meme_collection FROM season_events "
                "WHERE meme_collection IS NOT NULL"
            )
        ):
            key = (row[0] or "").strip()
            if key:
                keys.add(key)
    for key in sorted(keys):
        conn.execute(
            sa.text("INSERT INTO meme_collections (key) VALUES (:key)"),
            {"key": key[:64]},
        )


def downgrade() -> None:
    op.drop_table("meme_collections")
