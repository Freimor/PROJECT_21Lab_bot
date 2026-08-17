"""Staff blessing: +1 respect to a community member."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from lab21_bot.data import phrase, setting_default
from lab21_bot.models import Blessing, LedgerType, User
from lab21_bot.services.access import Permission, require_permission
from lab21_bot.services.economy import EconomyError, reward_participant
from lab21_bot.services.settings import get_int_setting


class BlessError(RuntimeError):
    pass


async def bless_member(
    session: AsyncSession,
    actor: User,
    target: User,
    *,
    now: datetime | None = None,
) -> Blessing:
    require_permission(actor, Permission.MANAGE_ECONOMY)
    if actor.telegram_id == target.telegram_id:
        raise BlessError(phrase("bless", "self"))
    if target.staff_role is not None or not target.is_approved or not target.is_active:
        raise BlessError(phrase("bless", "invalid_target"))

    now = now or datetime.now(UTC)
    daily_limit = await get_int_setting(
        session, "bless_daily_limit", int(setting_default("bless_daily_limit"))
    )
    cooldown_days = await get_int_setting(
        session, "bless_pair_cooldown_days", int(setting_default("bless_pair_cooldown_days"))
    )

    if daily_limit > 0:
        day_start = now - timedelta(hours=24)
        used = await session.scalar(
            select(func.count(Blessing.id)).where(
                Blessing.from_id == actor.telegram_id,
                Blessing.created_at >= day_start,
            )
        )
        if int(used or 0) >= daily_limit:
            raise BlessError(phrase("bless", "daily_limit"))

    if cooldown_days > 0:
        pair_start = now - timedelta(days=cooldown_days)
        recent = await session.scalar(
            select(Blessing.id).where(
                Blessing.from_id == actor.telegram_id,
                Blessing.to_id == target.telegram_id,
                Blessing.created_at >= pair_start,
            )
        )
        if recent is not None:
            raise BlessError(phrase("bless", "pair_cooldown", days=cooldown_days))

    try:
        await reward_participant(
            session,
            target.telegram_id,
            grace=0,
            respect=1,
            reason="Благословение",
            idempotency_key=f"bless:{actor.telegram_id}:{target.telegram_id}:{now.date().isoformat()}",
            grace_entry_type=LedgerType.GRANT,
        )
    except EconomyError as exc:
        raise BlessError(str(exc)) from exc

    row = Blessing(from_id=actor.telegram_id, to_id=target.telegram_id, created_at=now)
    session.add(row)
    await session.flush()
    return row
