"""Marketplace listings, pledges, and counter deals.

Revision ID: 20261001_0035
Revises: 20260925_0034
Create Date: 2026-10-01
"""

from __future__ import annotations

import json
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy import bindparam

from alembic import op

revision: str = "20261001_0035"
down_revision: str | None = "20260925_0034"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_FAIR_PERMS = ("fair_moderate", "fair_warehouse", "fair_disputes")
_FAIR_ROLES = ("lord", "magister", "watcher")


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("sales_mode", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "users",
        sa.Column("market_intro_seen", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_table(
        "listings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("seller_id", sa.BigInteger(), sa.ForeignKey("users.telegram_id"), nullable=True),
        sa.Column("created_by", sa.BigInteger(), sa.ForeignKey("users.telegram_id"), nullable=False),
        sa.Column("title", sa.String(length=160), nullable=False),
        sa.Column("category", sa.String(length=32), nullable=False, server_default="other"),
        sa.Column("tags", sa.JSON(), nullable=False),
        sa.Column("summary", sa.String(length=400), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("photos", sa.JSON(), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("currency", sa.String(length=16), nullable=False),
        sa.Column("price", sa.Integer(), nullable=False),
        sa.Column("stock", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("reserved", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("collection_phase", sa.String(length=32), nullable=False),
        sa.Column("batch_threshold", sa.Integer(), nullable=True),
        sa.Column("collection_ends_on", sa.Date(), nullable=True),
        sa.Column("handover_on", sa.Date(), nullable=True),
        sa.Column("removal_reason", sa.Text(), nullable=True),
        sa.Column("removed_by", sa.BigInteger(), sa.ForeignKey("users.telegram_id"), nullable=True),
        sa.Column("fair_message_id", sa.BigInteger(), nullable=True),
        sa.Column("fair_chat_id", sa.BigInteger(), nullable=True),
        sa.Column("fair_file_id", sa.String(length=255), nullable=True),
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
    )
    op.create_index("ix_listings_status_kind", "listings", ["status", "kind"])
    op.create_table(
        "listing_pledges",
        sa.Column(
            "listing_id",
            sa.Integer(),
            sa.ForeignKey("listings.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.telegram_id"), primary_key=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_table(
        "market_deals",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("listing_id", sa.Integer(), sa.ForeignKey("listings.id"), nullable=False),
        sa.Column("buyer_id", sa.BigInteger(), sa.ForeignKey("users.telegram_id"), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("unit_price", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("qr_token", sa.String(length=32), nullable=False),
        sa.Column("dispute_text", sa.Text(), nullable=True),
        sa.Column("issued_by", sa.BigInteger(), sa.ForeignKey("users.telegram_id"), nullable=True),
        sa.Column("resolved_by", sa.BigInteger(), sa.ForeignKey("users.telegram_id"), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("qr_token", name="uq_market_deals_qr_token"),
    )
    op.create_index("ix_market_deals_buyer", "market_deals", ["buyer_id", "status"])
    op.create_index("ix_market_deals_listing", "market_deals", ["listing_id"])
    _grant_fair_permissions()


def _grant_fair_permissions() -> None:
    conn = op.get_bind()
    if not sa.inspect(conn).has_table("role_defs"):
        return
    rows = conn.execute(sa.text("SELECT id, permissions FROM role_defs")).mappings().all()
    stmt = sa.text("UPDATE role_defs SET permissions = :perms WHERE id = :id").bindparams(
        bindparam("perms", type_=sa.JSON())
    )
    for row in rows:
        role_id = str(row["id"])
        if role_id not in _FAIR_ROLES:
            continue
        raw = row["permissions"]
        if raw is None:
            current: list[str] = []
        elif isinstance(raw, str):
            loaded = json.loads(raw)
            current = list(loaded) if isinstance(loaded, list) else []
        else:
            current = [str(item) for item in raw]
        changed = False
        for perm in _FAIR_PERMS:
            if perm not in current:
                current.append(perm)
                changed = True
        if changed:
            conn.execute(stmt, {"perms": current, "id": role_id})


def downgrade() -> None:
    op.drop_index("ix_market_deals_listing", table_name="market_deals")
    op.drop_index("ix_market_deals_buyer", table_name="market_deals")
    op.drop_table("market_deals")
    op.drop_table("listing_pledges")
    op.drop_index("ix_listings_status_kind", table_name="listings")
    op.drop_table("listings")
    op.drop_column("users", "market_intro_seen")
    op.drop_column("users", "sales_mode")
