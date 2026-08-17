"""Seasonal events: meme collections, phrases, announcements."""

from __future__ import annotations

import hashlib
from datetime import date, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from lab21_bot.data import phrase
from lab21_bot.models import SeasonEvent, User
from lab21_bot.services.access import Permission, require_permission

_ANNOUNCE_LIMIT = 4096

SEASON_ANNOUNCE_PLACEHOLDERS: tuple[dict[str, str], ...] = (
    {"token": "{title}", "hint": "Название сезона"},
    {"token": "{description}", "hint": "Описание сезона"},
    {"token": "{starts_on}", "hint": "Дата начала, ГГГГ-ММ-ДД"},
    {"token": "{ends_on}", "hint": "Дата окончания, ГГГГ-ММ-ДД"},
    {"token": "{code}", "hint": "Код сезона, например halloween"},
)

_MONTH_LABELS = (
    "янв",
    "фев",
    "мар",
    "апр",
    "май",
    "июн",
    "июл",
    "авг",
    "сен",
    "окт",
    "ноя",
    "дек",
)
_BAR_COLORS = (
    "#ff7a25",
    "#e8a04a",
    "#7ec8e3",
    "#c4b5fd",
    "#86efac",
    "#f9a8d4",
    "#fde68a",
    "#93c5fd",
)
_MIN_BAR_PCT = 0.85


class SeasonError(RuntimeError):
    pass


def format_season_announce(season: SeasonEvent, kind: str) -> str:
    """Build the public start/end post. Custom admin text wins; else phrases.json."""
    custom = (
        season.start_message if kind == "start" else season.end_message
    ) or ""
    template = custom.strip() or phrase("seasons", kind)
    fields = {
        "title": season.title,
        "description": season.description or "",
        "starts_on": season.starts_on.isoformat() if season.starts_on else "",
        "ends_on": season.ends_on.isoformat() if season.ends_on else "",
        "code": season.code,
    }
    text = template
    for item in SEASON_ANNOUNCE_PLACEHOLDERS:
        key = item["token"].strip("{}")
        text = text.replace(item["token"], str(fields[key]))
    return text.strip()[:_ANNOUNCE_LIMIT]


def season_bar_color(code: str) -> str:
    digest = hashlib.md5((code or "").encode("utf-8"), usedforsecurity=False).hexdigest()
    return _BAR_COLORS[int(digest[:8], 16) % len(_BAR_COLORS)]


def build_season_year_map(
    seasons: list[SeasonEvent],
    *,
    year: int,
    today: date | None = None,
) -> dict[str, Any]:
    """Layout data for the admin year map: month ticks and clipped season bars."""
    today = today or date.today()
    jan1 = date(year, 1, 1)
    dec31 = date(year, 12, 31)
    days = (dec31 - jan1).days + 1
    years = {today.year, year}
    for season in seasons:
        years.add(season.starts_on.year)
        years.add(season.ends_on.year)

    months = []
    for month in range(1, 13):
        start = date(year, month, 1)
        end = date(year, month + 1, 1) - timedelta(days=1) if month < 12 else dec31
        months.append(
            {
                "n": month,
                "label": _MONTH_LABELS[month - 1],
                "left": round((start - jan1).days / days * 100, 4),
                "width": round(((end - start).days + 1) / days * 100, 4),
            }
        )

    today_pct: float | None = None
    if today.year == year:
        today_pct = round(((today - jan1).days + 0.5) / days * 100, 4)

    rows: list[dict[str, Any]] = []
    for season in seasons:
        if season.ends_on < jan1 or season.starts_on > dec31:
            continue
        vis_start = max(season.starts_on, jan1)
        vis_end = min(season.ends_on, dec31)
        left = (vis_start - jan1).days / days * 100
        width = ((vis_end - vis_start).days + 1) / days * 100
        width = max(width, _MIN_BAR_PCT)
        if left + width > 100:
            left = max(0.0, 100.0 - width)
        if not season.is_enabled:
            state = "off"
        elif season.starts_on <= today <= season.ends_on:
            state = "active"
        elif season.ends_on < today:
            state = "past"
        else:
            state = "upcoming"
        rows.append(
            {
                "id": season.id,
                "code": season.code,
                "title": season.title,
                "starts_on": season.starts_on,
                "ends_on": season.ends_on,
                "meme_collection": season.meme_collection,
                "is_enabled": season.is_enabled,
                "left": round(left, 4),
                "width": round(width, 4),
                "color": season_bar_color(season.code),
                "state": state,
                "continues_left": season.starts_on < jan1,
                "continues_right": season.ends_on > dec31,
            }
        )
    rows.sort(key=lambda row: (row["starts_on"], row["id"] or 0))
    return {
        "year": year,
        "years": sorted(years),
        "days": days,
        "months": months,
        "today_pct": today_pct,
        "today": today,
        "rows": rows,
    }


async def list_seasons(session: AsyncSession) -> list[SeasonEvent]:
    return list(
        await session.scalars(select(SeasonEvent).order_by(SeasonEvent.starts_on.desc()))
    )


async def get_season(session: AsyncSession, season_id: int) -> SeasonEvent:
    season = await session.get(SeasonEvent, season_id)
    if season is None:
        raise SeasonError("Сезон не найден")
    return season


async def active_season(
    session: AsyncSession,
    *,
    today: date | None = None,
) -> SeasonEvent | None:
    today = today or date.today()
    return await session.scalar(
        select(SeasonEvent)
        .where(
            SeasonEvent.is_enabled.is_(True),
            SeasonEvent.starts_on <= today,
            SeasonEvent.ends_on >= today,
        )
        .order_by(SeasonEvent.starts_on.desc())
        .limit(1)
    )


async def seasons_needing_reminder(
    session: AsyncSession,
    *,
    today: date | None = None,
    days_before: int = 3,
) -> list[SeasonEvent]:
    today = today or date.today()
    target = today + timedelta(days=days_before)
    return list(
        await session.scalars(
            select(SeasonEvent).where(
                SeasonEvent.is_enabled.is_(True),
                SeasonEvent.reminder_sent.is_(False),
                SeasonEvent.starts_on == target,
            )
        )
    )


async def seasons_needing_start_announce(
    session: AsyncSession,
    *,
    today: date | None = None,
) -> list[SeasonEvent]:
    today = today or date.today()
    return list(
        await session.scalars(
            select(SeasonEvent).where(
                SeasonEvent.is_enabled.is_(True),
                SeasonEvent.start_announced.is_(False),
                SeasonEvent.starts_on <= today,
                SeasonEvent.ends_on >= today,
            )
        )
    )


async def seasons_needing_end_announce(
    session: AsyncSession,
    *,
    today: date | None = None,
) -> list[SeasonEvent]:
    today = today or date.today()
    yesterday = today - timedelta(days=1)
    return list(
        await session.scalars(
            select(SeasonEvent).where(
                SeasonEvent.is_enabled.is_(True),
                SeasonEvent.end_announced.is_(False),
                SeasonEvent.ends_on == yesterday,
            )
        )
    )


async def create_season(
    session: AsyncSession,
    actor: User,
    *,
    code: str,
    title: str,
    description: str,
    starts_on: date,
    ends_on: date,
    meme_collection: str = "default",
    phrases_key: str = "",
    start_message: str = "",
    end_message: str = "",
) -> SeasonEvent:
    require_permission(actor, Permission.MANAGE_SETTINGS)
    code = code.strip().lower().replace(" ", "_")
    title = title.strip()
    if not code or not title:
        raise SeasonError("Код и название обязательны")
    if ends_on < starts_on:
        raise SeasonError("Дата конца раньше начала")
    existing = await session.scalar(select(SeasonEvent).where(SeasonEvent.code == code))
    if existing is not None:
        raise SeasonError("Сезон с таким кодом уже есть")
    from lab21_bot.services.templates import ensure_meme_collection, normalize_collection_key

    collection = normalize_collection_key(meme_collection)
    await ensure_meme_collection(session, collection)
    season = SeasonEvent(
        code=code,
        title=title[:200],
        description=description.strip(),
        starts_on=starts_on,
        ends_on=ends_on,
        meme_collection=collection,
        phrases_key=(phrases_key or "").strip(),
        start_message=(start_message or "").strip(),
        end_message=(end_message or "").strip(),
        is_enabled=True,
    )
    session.add(season)
    await session.flush()
    return season


async def update_season(
    session: AsyncSession,
    actor: User,
    season_id: int,
    *,
    title: str | None = None,
    description: str | None = None,
    starts_on: date | None = None,
    ends_on: date | None = None,
    meme_collection: str | None = None,
    phrases_key: str | None = None,
    start_message: str | None = None,
    end_message: str | None = None,
    is_enabled: bool | None = None,
) -> SeasonEvent:
    require_permission(actor, Permission.MANAGE_SETTINGS)
    season = await get_season(session, season_id)
    if title is not None:
        season.title = title.strip()[:200]
    if description is not None:
        season.description = description.strip()
    if starts_on is not None:
        season.starts_on = starts_on
    if ends_on is not None:
        season.ends_on = ends_on
    if season.ends_on < season.starts_on:
        raise SeasonError("Дата конца раньше начала")
    if meme_collection is not None:
        from lab21_bot.services.templates import ensure_meme_collection, normalize_collection_key

        collection = normalize_collection_key(meme_collection)
        await ensure_meme_collection(session, collection)
        season.meme_collection = collection
    if phrases_key is not None:
        season.phrases_key = phrases_key.strip()
    if start_message is not None:
        season.start_message = start_message.strip()
    if end_message is not None:
        season.end_message = end_message.strip()
    if is_enabled is not None:
        season.is_enabled = is_enabled
    await session.flush()
    return season


async def delete_season(session: AsyncSession, actor: User, season_id: int) -> None:
    require_permission(actor, Permission.MANAGE_SETTINGS)
    season = await get_season(session, season_id)
    await session.delete(season)
    await session.flush()
