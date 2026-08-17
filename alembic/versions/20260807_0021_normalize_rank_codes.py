"""Normalize legacy UPPERCASE rank/role codes and backfill join base grace.

Revision ID: 20260807_0021
Revises: 20260807_0020
Create Date: 2026-08-07
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260807_0021"
down_revision: str | None = "20260807_0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    conn = op.get_bind()
    # Legacy SQLAlchemy Enum sometimes persisted Enum.name (NOVICE) not value (novice).
    conn.execute(sa.text("UPDATE users SET rank = lower(rank) WHERE rank <> lower(rank)"))
    conn.execute(
        sa.text(
            "UPDATE users SET staff_role = lower(staff_role) "
            "WHERE staff_role IS NOT NULL AND staff_role <> lower(staff_role)"
        )
    )
    conn.execute(
        sa.text("UPDATE products SET min_rank = lower(min_rank) WHERE min_rank <> lower(min_rank)")
    )
    conn.execute(
        sa.text(
            "UPDATE products SET grants_rank = lower(grants_rank) "
            "WHERE grants_rank IS NOT NULL AND grants_rank <> lower(grants_rank)"
        )
    )

    # Backfill base grace for community members approved without a join-base ledger row.
    rows = conn.execute(
        sa.text(
            """
            SELECT u.telegram_id, u.balance, COALESCE(r.base_grace, 0) AS base_grace,
                   a.id AS application_id
            FROM users u
            LEFT JOIN rank_defs r ON r.id = u.rank
            LEFT JOIN LATERAL (
                SELECT ja.id
                FROM join_applications ja
                WHERE ja.user_id = u.telegram_id
                  AND ja.kind = 'community'
                  AND ja.status = 'approved'
                ORDER BY ja.decided_at DESC NULLS LAST, ja.id DESC
                LIMIT 1
            ) a ON TRUE
            WHERE u.is_approved IS TRUE
              AND u.staff_role IS NULL
              AND u.is_active IS TRUE
              AND COALESCE(r.base_grace, 0) > 0
              AND u.balance < COALESCE(r.base_grace, 0)
              AND NOT EXISTS (
                    SELECT 1 FROM ledger_entries le
                    WHERE le.account_user_id = u.telegram_id
                      AND (
                        le.idempotency_key LIKE 'join-base-grace:%'
                        OR le.reason LIKE 'Базовая благодать при вступлении%'
                      )
              )
            """
        )
    ).mappings().all()

    for row in rows:
        user_id = int(row["telegram_id"])
        base = int(row["base_grace"])
        balance = int(row["balance"] or 0)
        grant = base - balance
        if grant <= 0:
            continue
        app_id = row["application_id"]
        idem = f"join-base-grace:{app_id}" if app_id else f"join-base-grace-backfill:{user_id}"
        group = f"join-base:{app_id}" if app_id else f"join-base-backfill:{user_id}"
        new_balance = balance + grant
        conn.execute(
            sa.text("UPDATE users SET balance = :balance WHERE telegram_id = :uid"),
            {"balance": new_balance, "uid": user_id},
        )
        conn.execute(
            sa.text(
                """
                INSERT INTO ledger_entries (
                    transaction_group, idempotency_key, initiator_id, account_user_id,
                    counterparty_id, delta, balance_after, entry_type, reason
                ) VALUES (
                    :group, :idem, NULL, :uid,
                    NULL, :delta, :balance_after, 'grant', :reason
                )
                """
            ),
            {
                "group": group,
                "idem": idem,
                "uid": user_id,
                "delta": grant,
                "balance_after": new_balance,
                "reason": "Базовая благодать при вступлении (доначисление)",
            },
        )


def downgrade() -> None:
    # Irreversible data repair.
    pass
