"""Shared admin time-window presets."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

PeriodKey = Literal["today", "week", "year", "all"]

PERIOD_LABELS: dict[PeriodKey, str] = {
    "today": "Сегодня",
    "week": "Неделя",
    "year": "Год",
    "all": "Все время",
}

PERIOD_KEYS: tuple[PeriodKey, ...] = ("today", "week", "year", "all")


def parse_period(raw: str | None, *, default: PeriodKey = "all") -> PeriodKey:
    if raw in PERIOD_LABELS:
        return raw  # type: ignore[return-value]
    return default


def period_since(
    period: PeriodKey,
    *,
    now: datetime | None = None,
    tz: ZoneInfo | None = None,
) -> datetime | None:
    """Start of the window in UTC, or None for all time."""
    if period == "all":
        return None
    current = now or datetime.now(UTC)
    if tz is not None:
        local = current.astimezone(tz)
        start_local = local.replace(hour=0, minute=0, second=0, microsecond=0)
        if period == "today":
            return start_local.astimezone(UTC)
        if period == "week":
            return (start_local - timedelta(days=6)).astimezone(UTC)
        if period == "year":
            return start_local.replace(month=1, day=1).astimezone(UTC)
    if period == "today":
        return current - timedelta(days=1)
    if period == "week":
        return current - timedelta(days=7)
    return current - timedelta(days=365)


def parse_date_bound(raw: str | None, *, end_of_day: bool = False) -> datetime | None:
    if not raw or not raw.strip():
        return None
    try:
        day = datetime.strptime(raw.strip(), "%Y-%m-%d").replace(tzinfo=UTC)
    except ValueError:
        return None
    if end_of_day:
        return day + timedelta(days=1) - timedelta(microseconds=1)
    return day
