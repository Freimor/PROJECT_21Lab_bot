"""Daily grace adjustment toward rank base (floor) and cap (ceiling)."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from lab21_bot.data import rank_base_grace, rank_cap_grace, setting_default
from lab21_bot.models import LedgerEntry, LedgerType, User
from lab21_bot.services.settings import get_int_setting


def refill_amount(*, balance: int, base: int, percent: int) -> int:
    """How much to grant toward base: percent of base, not above base."""
    if base <= 0 or balance >= base or percent <= 0:
        return 0
    step = max(1, base * percent // 100)
    return min(step, base - balance)


def decay_amount(*, balance: int, cap: int, percent: int) -> int:
    """How much to withdraw toward cap: percent of cap, not below cap."""
    if cap <= 0 or balance <= cap or percent <= 0:
        return 0
    step = max(1, cap * percent // 100)
    return min(step, balance - cap)


async def refill_grace_toward_base(session: AsyncSession) -> list[tuple[User, int]]:
    """Backward-compatible name: floor refill only."""
    refill_updated, _decay_updated = await adjust_grace_bounds(session)
    return refill_updated


async def adjust_grace_bounds(
    session: AsyncSession,
) -> tuple[list[tuple[User, int]], list[tuple[User, int]]]:
    """Pull balances up to base and down to cap once per day."""
    refill_percent = await get_int_setting(
        session,
        "grace_refill_percent",
        setting_default("grace_refill_percent"),
    )
    decay_percent = await get_int_setting(
        session,
        "grace_decay_percent",
        setting_default("grace_decay_percent"),
    )
    rows = await session.scalars(
        select(User)
        .where(
            User.is_approved.is_(True),
            User.is_active.is_(True),
            User.staff_role.is_(None),
        )
        .with_for_update()
    )
    refilled: list[tuple[User, int]] = []
    decayed: list[tuple[User, int]] = []
    for user in rows:
        base = rank_base_grace(str(user.rank))
        cap = rank_cap_grace(str(user.rank))

        grant = refill_amount(balance=user.balance, base=base, percent=refill_percent)
        if grant > 0:
            user.balance += grant
            session.add(
                LedgerEntry(
                    transaction_group=str(uuid.uuid4()),
                    idempotency_key=None,
                    initiator_id=None,
                    account_user_id=user.telegram_id,
                    delta=grant,
                    balance_after=user.balance,
                    entry_type=LedgerType.GRANT,
                    reason=f"Ежедневное пополнение к базовой 🙏 ({refill_percent}%)",
                )
            )
            refilled.append((user, grant))

        cut = decay_amount(balance=user.balance, cap=cap, percent=decay_percent)
        if cut > 0:
            user.balance -= cut
            session.add(
                LedgerEntry(
                    transaction_group=str(uuid.uuid4()),
                    idempotency_key=None,
                    initiator_id=None,
                    account_user_id=user.telegram_id,
                    delta=-cut,
                    balance_after=user.balance,
                    entry_type=LedgerType.WITHDRAW,
                    reason=f"Ежедневное снижение к верхнему порогу 🙏 ({decay_percent}%)",
                )
            )
            decayed.append((user, cut))

    await session.flush()
    return refilled, decayed
