"""Admin notification toggles, staff-chat delivery, and browser event feed."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, Literal

import structlog
from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.types import InlineKeyboardMarkup
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from lab21_bot.config import Settings
from lab21_bot.models import AdminAction, AdminNotifyEvent, BotSetting, User
from lab21_bot.services.access import Permission, require_permission
from lab21_bot.services.notify import TelegramSendError, send_telegram_message

logger = structlog.get_logger(__name__)

SETTINGS_KEY = "admin_notifications"

EventType = Literal[
    "llm_done",
    "join_community",
    "join_staff",
    "content_queue",
    "shop_order",
    "feedback",
]

EVENT_TYPES: tuple[EventType, ...] = (
    "llm_done",
    "join_community",
    "join_staff",
    "content_queue",
    "shop_order",
    "feedback",
)

EVENT_LABELS: dict[EventType, str] = {
    "llm_done": "Окончание генерации LLM",
    "join_community": "Новая заявка участника",
    "join_staff": "Новая заявка сотрудника",
    "content_queue": "Пост/мем в очереди модерации",
    "shop_order": "Новый заказ в магазине",
    "feedback": "Баг или предложение",
}

Channel = Literal["staff_chat", "browser"]
CHANNELS: tuple[Channel, ...] = ("staff_chat", "browser")

FEED_MAX_AGE = timedelta(hours=24)


def default_notification_prefs() -> dict[str, dict[str, bool]]:
    flags = {key: True for key in EVENT_TYPES}
    return {"staff_chat": dict(flags), "browser": dict(flags)}


def _normalize_prefs(raw: Any) -> dict[str, dict[str, bool]]:
    base = default_notification_prefs()
    if not isinstance(raw, dict):
        return base
    for channel in CHANNELS:
        block = raw.get(channel)
        if not isinstance(block, dict):
            continue
        for event in EVENT_TYPES:
            if event in block:
                base[channel][event] = bool(block[event])
    return base


async def get_notification_prefs(session: AsyncSession) -> dict[str, dict[str, bool]]:
    setting = await session.get(BotSetting, SETTINGS_KEY)
    if setting is None:
        return default_notification_prefs()
    return _normalize_prefs(setting.value)


async def save_notification_prefs(
    session: AsyncSession,
    actor: User,
    prefs: dict[str, dict[str, bool]],
) -> dict[str, dict[str, bool]]:
    require_permission(actor, Permission.MANAGE_SETTINGS)
    cleaned = _normalize_prefs(prefs)
    setting = await session.get(BotSetting, SETTINGS_KEY)
    if setting is None:
        setting = BotSetting(
            key=SETTINGS_KEY,
            value=cleaned,
            updated_by=actor.telegram_id,
        )
        session.add(setting)
    else:
        setting.value = cleaned
        setting.updated_by = actor.telegram_id
    session.add(
        AdminAction(
            actor_id=actor.telegram_id,
            action="set_setting",
            details={"key": SETTINGS_KEY, "value": cleaned},
        )
    )
    await session.flush()
    return cleaned


def prefs_from_form(form: dict[str, Any]) -> dict[str, dict[str, bool]]:
    """Build prefs from checkbox names like staff_chat_llm_done."""
    result = default_notification_prefs()
    for channel in CHANNELS:
        for event in EVENT_TYPES:
            result[channel][event] = False
    for channel in CHANNELS:
        for event in EVENT_TYPES:
            key = f"{channel}_{event}"
            if key in form:
                result[channel][event] = True
    return result


def admin_path(settings: Settings, path: str) -> str:
    base = settings.admin_base_url.rstrip("/")
    if not path.startswith("/"):
        path = f"/{path}"
    return f"{base}{path}"


async def notify_admin_event(
    session: AsyncSession,
    settings: Settings,
    event_type: EventType,
    *,
    title: str,
    body: str,
    link: str | None = None,
    bot: Bot | None = None,
    reply_markup: InlineKeyboardMarkup | None = None,
) -> None:
    """Send to staff chat and/or browser feed according to toggles."""
    if event_type not in EVENT_TYPES:
        return
    prefs = await get_notification_prefs(session)
    staff_on = prefs["staff_chat"].get(event_type, True)
    browser_on = prefs["browser"].get(event_type, True)

    if staff_on and settings.staff_chat_id:
        text = title if not body else f"{title}\n{body}"
        if link:
            text = f"{text}\n{admin_path(settings, link)}"
        try:
            if bot is not None:
                await bot.send_message(
                    settings.staff_chat_id,
                    text,
                    reply_markup=reply_markup,
                )
            else:
                token = settings.telegram_bot_token.get_secret_value()
                await send_telegram_message(token, settings.staff_chat_id, text)
        except (TelegramBadRequest, TelegramForbiddenError, TelegramSendError) as exc:
            logger.info(
                "admin_notify_staff_failed",
                event_type=event_type,
                error=str(exc),
            )
        except Exception as exc:
            logger.info(
                "admin_notify_staff_failed",
                event_type=event_type,
                error=str(exc),
            )

    if browser_on:
        session.add(
            AdminNotifyEvent(
                event_type=event_type,
                title=title[:200],
                body=(body or "")[:2000],
                link=link,
            )
        )
        await session.flush()


async def list_notify_feed(
    session: AsyncSession,
    *,
    since_id: int = 0,
    limit: int = 50,
) -> list[AdminNotifyEvent]:
    prefs = await get_notification_prefs(session)
    enabled = {key for key, on in prefs["browser"].items() if on}
    if not enabled:
        return []
    cutoff = datetime.now(UTC) - FEED_MAX_AGE
    rows = (
        await session.scalars(
            select(AdminNotifyEvent)
            .where(
                AdminNotifyEvent.id > since_id,
                AdminNotifyEvent.created_at >= cutoff,
                AdminNotifyEvent.event_type.in_(enabled),
            )
            .order_by(AdminNotifyEvent.id.asc())
            .limit(limit)
        )
    ).all()
    return list(rows)


async def feed_latest_id(session: AsyncSession) -> int:
    value = await session.scalar(select(AdminNotifyEvent.id).order_by(AdminNotifyEvent.id.desc()).limit(1))
    return int(value or 0)
