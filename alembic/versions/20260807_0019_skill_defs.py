"""Skill catalog table seeded from skills.json.

Revision ID: 20260807_0019
Revises: 20260807_0018
Create Date: 2026-08-07
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

import sqlalchemy as sa
from alembic import op

revision: str = "20260807_0019"
down_revision: str | None = "20260807_0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _seed_skills() -> list[dict]:
    candidates = [
        Path("/app/src/lab21_bot/data/skills.json"),
        Path(__file__).resolve().parents[2] / "src" / "lab21_bot" / "data" / "skills.json",
    ]
    for path in candidates:
        if path.is_file():
            data = json.loads(path.read_text(encoding="utf-8"))
            skills = data.get("skills", [])
            return [item for item in skills if isinstance(item, dict) and item.get("id")]
    return []


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "skill_defs" not in inspector.get_table_names():
        op.create_table(
            "skill_defs",
            sa.Column("id", sa.String(length=64), primary_key=True),
            sa.Column("title", sa.String(length=200), nullable=False),
            sa.Column("description", sa.Text(), nullable=False, server_default=""),
            sa.Column("requires_validation", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("validation_description", sa.Text(), nullable=False, server_default=""),
            sa.Column("level", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("grace_price", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("respect_reward", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )

    # Seed only when empty.
    conn = op.get_bind()
    count = conn.execute(sa.text("SELECT COUNT(*) FROM skill_defs")).scalar()
    if not count:
        rows = _seed_skills()
        if rows:
            op.bulk_insert(
                sa.table(
                    "skill_defs",
                    sa.column("id", sa.String),
                    sa.column("title", sa.String),
                    sa.column("description", sa.Text),
                    sa.column("requires_validation", sa.Boolean),
                    sa.column("validation_description", sa.Text),
                    sa.column("level", sa.Integer),
                    sa.column("grace_price", sa.Integer),
                    sa.column("respect_reward", sa.Integer),
                ),
                [
                    {
                        "id": str(item["id"]),
                        "title": str(item.get("title") or item["id"]),
                        "description": str(item.get("description") or ""),
                        "requires_validation": bool(item.get("requires_validation")),
                        "validation_description": str(item.get("validation_description") or ""),
                        "level": int(item.get("level") or 1),
                        "grace_price": int(item.get("grace_price") or 0),
                        "respect_reward": int(item.get("respect_reward") or 0),
                    }
                    for item in rows
                ],
            )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "skill_defs" in inspector.get_table_names():
        op.drop_table("skill_defs")
