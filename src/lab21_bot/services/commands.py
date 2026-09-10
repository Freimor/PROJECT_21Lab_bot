from __future__ import annotations

from typing import Any

import structlog
from aiogram import Bot
from aiogram.types import BotCommand, BotCommandScopeChat, BotCommandScopeDefault

from lab21_bot.models import User
from lab21_bot.telegram_client import telegram_api_post

logger = structlog.get_logger(__name__)


def commands_for_user(user: User) -> list[BotCommand]:
    return [BotCommand(command="start", description="Открыть Lab21")]


def commands_payload(user: User) -> list[dict[str, str]]:
    return [
        {"command": item.command, "description": item.description}
        for item in commands_for_user(user)
    ]


async def clear_default_commands(bot: Bot) -> None:
    await bot.set_my_commands([], scope=BotCommandScopeDefault())


async def sync_user_commands(bot: Bot, user: User) -> None:
    scope = BotCommandScopeChat(chat_id=user.telegram_id)
    await bot.set_my_commands(commands_for_user(user), scope=scope)


async def sync_user_commands_http(bot_token: str, user: User) -> None:
    payload: dict[str, Any] = {
        "commands": commands_payload(user),
        "scope": {"type": "chat", "chat_id": user.telegram_id},
    }
    try:
        body = await telegram_api_post(bot_token, "setMyCommands", payload, request_timeout=20.0)
        if not body.get("ok"):
            logger.info(
                "telegram_set_commands_failed",
                user_id=user.telegram_id,
                error=body.get("description"),
            )
    except Exception as exc:
        logger.info(
            "telegram_set_commands_failed",
            user_id=user.telegram_id,
            error=str(exc),
        )
