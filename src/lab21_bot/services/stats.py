from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from lab21_bot.models import (
    ContentItem,
    ContentStatus,
    LedgerEntry,
    LedgerType,
    Order,
    OrderStatus,
    User,
)


@dataclass(frozen=True, slots=True)
class DashboardStats:
    users_total: int
    users_active: int
    balance_sum: int
    orders_pending: int
    orders_fulfilled: int
    content_moderation: int
    grants_7d: int
    grants_30d: int
    withdraws_7d: int
    withdraws_30d: int
    purchases_7d: int
    purchases_30d: int


async def _count(session: AsyncSession, statement: Select[tuple[int]]) -> int:
    value = await session.scalar(statement)
    return int(value or 0)


async def _ledger_sum(
    session: AsyncSession,
    entry_type: LedgerType,
    *,
    since: datetime,
    absolute: bool = False,
) -> int:
    column: ColumnElement[int] = (
        func.abs(LedgerEntry.delta) if absolute else LedgerEntry.delta  # type: ignore[assignment]
    )
    value = await session.scalar(
        select(func.coalesce(func.sum(column), 0)).where(
            LedgerEntry.entry_type == entry_type,
            LedgerEntry.created_at >= since,
        )
    )
    return int(value or 0)


async def dashboard_stats(
    session: AsyncSession,
    *,
    now: datetime | None = None,
) -> DashboardStats:
    now = now or datetime.now(UTC)
    since_7d = now - timedelta(days=7)
    since_30d = now - timedelta(days=30)

    return DashboardStats(
        users_total=await _count(
            session,
            select(func.count()).select_from(User).where(User.is_approved.is_(True)),
        ),
        users_active=await _count(
            session,
            select(func.count())
            .select_from(User)
            .where(User.is_approved.is_(True), User.is_active.is_(True)),
        ),
        balance_sum=await _count(
            session,
            select(func.coalesce(func.sum(User.balance), 0))
            .select_from(User)
            .where(User.staff_role.is_(None), User.is_approved.is_(True)),
        ),
        orders_pending=await _count(
            session,
            select(func.count()).select_from(Order).where(Order.status == OrderStatus.PENDING),
        ),
        orders_fulfilled=await _count(
            session,
            select(func.count()).select_from(Order).where(Order.status == OrderStatus.FULFILLED),
        ),
        content_moderation=await _count(
            session,
            select(func.count())
            .select_from(ContentItem)
            .where(ContentItem.status == ContentStatus.MODERATION),
        ),
        grants_7d=await _ledger_sum(session, LedgerType.GRANT, since=since_7d),
        grants_30d=await _ledger_sum(session, LedgerType.GRANT, since=since_30d),
        withdraws_7d=await _ledger_sum(session, LedgerType.WITHDRAW, since=since_7d, absolute=True),
        withdraws_30d=await _ledger_sum(
            session, LedgerType.WITHDRAW, since=since_30d, absolute=True
        ),
        purchases_7d=await _ledger_sum(
            session, LedgerType.PURCHASE_RESERVE, since=since_7d, absolute=True
        ),
        purchases_30d=await _ledger_sum(
            session, LedgerType.PURCHASE_RESERVE, since=since_30d, absolute=True
        ),
    )
