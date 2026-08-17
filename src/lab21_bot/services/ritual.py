"""Daily bow / ritual streak."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from lab21_bot.data import phrase, random_phrase, setting_default
from lab21_bot.models import LedgerType, User
from lab21_bot.services.economy import EconomyError, reward_participant
from lab21_bot.services.settings import get_int_setting


class RitualError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class RitualResult:
    grace: int
    streak: int
    streak_bonus: bool
    message: str


async def perform_ritual(
    session: AsyncSession,
    user: User,
    *,
    tz: ZoneInfo,
    today: date | None = None,
) -> RitualResult:
    if not user.is_approved or user.staff_role is not None:
        raise RitualError(phrase("ritual", "denied"))

    today = today or date.today()
    # Align "today" with bot timezone when caller passes local date.
    _ = tz

    grace = await get_int_setting(session, "ritual_grace", int(setting_default("ritual_grace")))
    bonus_grace = await get_int_setting(
        session,
        "ritual_streak_bonus_grace",
        int(setting_default("ritual_streak_bonus_grace")),
    )

    last = user.ritual_last_at
    if last == today:
        raise RitualError(phrase("ritual", "already", streak=user.ritual_streak))

    if last is None or last < today - timedelta(days=1):
        user.ritual_streak = 1
    else:
        user.ritual_streak = int(user.ritual_streak or 0) + 1
    user.ritual_last_at = today

    total_grace = grace
    streak_bonus = user.ritual_streak > 0 and user.ritual_streak % 7 == 0
    respect = 0
    if streak_bonus:
        total_grace += bonus_grace
        respect = 1

    try:
        await reward_participant(
            session,
            user.telegram_id,
            grace=total_grace,
            respect=respect,
            reason="Ритуал приклонения",
            idempotency_key=f"ritual:{user.telegram_id}:{today.isoformat()}",
            grace_entry_type=LedgerType.GRANT,
        )
    except EconomyError as exc:
        raise RitualError(str(exc)) from exc

    line = random_phrase("ritual", "lines", streak=user.ritual_streak, grace=total_grace)
    message = phrase(
        "ritual",
        "ok",
        line=line,
        streak=user.ritual_streak,
        grace=total_grace,
    )
    return RitualResult(
        grace=total_grace,
        streak=user.ritual_streak,
        streak_bonus=streak_bonus,
        message=message,
    )
