"""Rare bot flavor: animations / reactions on milestones."""

from __future__ import annotations

import random
from datetime import date
from typing import Any

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.types import ReactionTypeEmoji

from lab21_bot.data import load_json, setting_default
from lab21_bot.services.presence import cooldown_remaining, set_cooldown


def flavor_media_data() -> dict[str, Any]:
    try:
        return load_json("flavor_media.json")
    except (OSError, TypeError, ValueError):
        return {"events": {}}


async def maybe_send_flavor(
    bot: Bot,
    *,
    event_key: str,
    user_id: int,
    chat_id: int | None = None,
    message_id: int | None = None,
    session=None,
) -> bool:
    """Return True if something was sent. At most one flavor per user per day."""
    day_key = f"flavor:{user_id}:{date.today().isoformat()}"
    if cooldown_remaining(day_key) > 0:
        return False

    chance_percent = 25
    if session is not None:
        try:
            from lab21_bot.services.settings import get_int_setting

            chance_percent = await get_int_setting(
                session,
                "flavor_chance_percent",
                int(setting_default("flavor_chance_percent")),
            )
        except Exception:
            chance_percent = int(setting_default("flavor_chance_percent"))
    if random.random() * 100 > chance_percent:
        return False

    events = flavor_media_data().get("events") or {}
    options = events.get(event_key) or []
    if not isinstance(options, list) or not options:
        return False
    pick = random.choice(options)
    if not isinstance(pick, dict):
        return False

    sent = False
    try:
        if pick.get("type") == "animation" and pick.get("file_id"):
            target = chat_id if chat_id is not None else user_id
            await bot.send_animation(target, pick["file_id"])
            sent = True
        elif (
            pick.get("type") == "reaction"
            and pick.get("emoji")
            and chat_id is not None
            and message_id is not None
        ):
            await bot.set_message_reaction(
                chat_id=chat_id,
                message_id=message_id,
                reaction=[ReactionTypeEmoji(emoji=str(pick["emoji"]))],
            )
            sent = True
    except (TelegramBadRequest, TelegramForbiddenError):
        return False

    if sent:
        set_cooldown(day_key, 86400)
    return sent
