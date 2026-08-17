"""Role and rank catalog tables seeded from ranks.json.

Revision ID: 20260807_0020
Revises: 20260807_0019
Create Date: 2026-08-07
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

import sqlalchemy as sa
from alembic import op

revision: str = "20260807_0020"
down_revision: str | None = "20260807_0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ALL_PERMS = [
    "manage_staff",
    "manage_settings",
    "manage_system",
    "manage_store",
    "manage_economy",
    "moderate_content",
    "moderate_orders",
    "create_staff_content",
]

_DEFAULT_ROLE_PERMISSIONS = {
    "lord": list(_ALL_PERMS),
    "magister": [p for p in _ALL_PERMS if p != "manage_system"],
    "tech_priest": ["manage_economy", "create_staff_content"],
    "watcher": ["moderate_content", "moderate_orders", "create_staff_content"],
}


def _ranks_json() -> dict:
    candidates = [
        Path("/app/src/lab21_bot/data/ranks.json"),
        Path(__file__).resolve().parents[2] / "src" / "lab21_bot" / "data" / "ranks.json",
    ]
    for path in candidates:
        if path.is_file():
            return json.loads(path.read_text(encoding="utf-8"))
    return {}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "role_defs" not in tables:
        op.create_table(
            "role_defs",
            sa.Column("id", sa.String(length=64), primary_key=True),
            sa.Column("label", sa.String(length=200), nullable=False),
            sa.Column("badge", sa.String(length=64), nullable=False, server_default="сотрудник"),
            sa.Column("color", sa.String(length=32), nullable=False, server_default="#6b7c93"),
            sa.Column("description", sa.Text(), nullable=False, server_default=""),
            sa.Column("permissions", sa.JSON(), nullable=False),
            sa.Column("is_unique", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )

    if "rank_defs" not in tables:
        op.create_table(
            "rank_defs",
            sa.Column("id", sa.String(length=64), primary_key=True),
            sa.Column("label", sa.String(length=200), nullable=False),
            sa.Column("level", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("color", sa.String(length=32), nullable=False, server_default="#a89878"),
            sa.Column("base_grace", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("cap_grace", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("can_transfer_grace", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )

    data = _ranks_json()
    conn = op.get_bind()

    if not conn.execute(sa.text("SELECT COUNT(*) FROM role_defs")).scalar():
        roles = data.get("roles") or {}
        if isinstance(roles, dict) and roles:
            op.bulk_insert(
                sa.table(
                    "role_defs",
                    sa.column("id", sa.String),
                    sa.column("label", sa.String),
                    sa.column("badge", sa.String),
                    sa.column("color", sa.String),
                    sa.column("description", sa.Text),
                    sa.column("permissions", sa.JSON),
                    sa.column("is_unique", sa.Boolean),
                    sa.column("sort_order", sa.Integer),
                ),
                [
                    {
                        "id": str(key),
                        "label": str(item.get("label") or key),
                        "badge": str(item.get("badge") or "сотрудник"),
                        "color": str(item.get("color") or "#6b7c93"),
                        "description": str(item.get("desc") or ""),
                        "permissions": list(_DEFAULT_ROLE_PERMISSIONS.get(str(key), [])),
                        "is_unique": str(key) == "lord",
                        "sort_order": index,
                    }
                    for index, (key, item) in enumerate(roles.items())
                    if isinstance(item, dict)
                ],
            )

    if not conn.execute(sa.text("SELECT COUNT(*) FROM rank_defs")).scalar():
        ranks = data.get("ranks") or {}
        if isinstance(ranks, dict) and ranks:
            op.bulk_insert(
                sa.table(
                    "rank_defs",
                    sa.column("id", sa.String),
                    sa.column("label", sa.String),
                    sa.column("level", sa.Integer),
                    sa.column("color", sa.String),
                    sa.column("base_grace", sa.Integer),
                    sa.column("cap_grace", sa.Integer),
                    sa.column("can_transfer_grace", sa.Boolean),
                    sa.column("sort_order", sa.Integer),
                ),
                [
                    {
                        "id": str(key),
                        "label": str(item.get("label") or key),
                        "level": int(item.get("level") or 0),
                        "color": str(item.get("color") or "#a89878"),
                        "base_grace": int(item.get("base_grace") or 0),
                        "cap_grace": int(item.get("cap_grace") or 0),
                        "can_transfer_grace": str(key) == "adept",
                        "sort_order": index,
                    }
                    for index, (key, item) in enumerate(ranks.items())
                    if isinstance(item, dict)
                ],
            )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "rank_defs" in tables:
        op.drop_table("rank_defs")
    if "role_defs" in tables:
        op.drop_table("role_defs")
