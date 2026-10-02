from __future__ import annotations

from typing import Any

import structlog
from aiogram import Bot
from aiogram.types import (
    BotCommand,
    BotCommandScopeAllGroupChats,
    BotCommandScopeAllPrivateChats,
    BotCommandScopeChat,
    BotCommandScopeDefault,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from lab21_bot.models import User
from lab21_bot.telegram_client import telegram_api_post

logger = structlog.get_logger(__name__)

# Private menu: /bow only, so a tap sends the ritual and Telegram does not add @bot.
MENU_COMMANDS: tuple[tuple[str, str], ...] = (
    ("bow", "Приклониться"),
)
# Forum topics share the group command list. Telegram inserts @bot itself.
GROUP_COMMANDS: tuple[tuple[str, str], ...] = (
    ("bow", "Приклониться"),
    ("bug", "Сообщить о баге"),
    ("upgrade", "Предложить улучшение"),
)


def _commands(pairs: list[tuple[str, str]]) -> list[BotCommand]:
    return [BotCommand(command=command, description=description) for command, description in pairs]


def commands_for_user(user: User) -> list[BotCommand]:
    pairs = list(MENU_COMMANDS)
    if user.staff_role is not None and user.can_use_testuser:
        label = (
            "Вернуться в свой аккаунт"
            if user.testuser_active
            else "Войти тестовым участником"
        )
        pairs.append(("testuser", label))
    return _commands(pairs)


def commands_payload(user: User) -> list[dict[str, str]]:
    return [
        {"command": item.command, "description": item.description}
        for item in commands_for_user(user)
    ]


async def sync_user_commands(bot: Bot, user: User) -> None:
    scope = BotCommandScopeChat(chat_id=user.telegram_id)
    await bot.set_my_commands(commands_for_user(user), scope=scope)


async def sync_command_menu(bot: Bot, session: AsyncSession) -> None:
    """Publish the slash-menu for private chats, groups, and known users.

    A per-user menu replaces the default one, so anyone who previously received
    only /start must be updated or typing / stays almost empty.
    """
    private = _commands(list(MENU_COMMANDS))
    group = _commands(list(GROUP_COMMANDS))
    await bot.set_my_commands([], scope=BotCommandScopeDefault())
    await bot.set_my_commands(private, scope=BotCommandScopeAllPrivateChats())
    await bot.set_my_commands(group, scope=BotCommandScopeAllGroupChats())
    users = await session.scalars(select(User))
    for user in users:
        try:
            await sync_user_commands(bot, user)
        except Exception as exc:
            logger.info(
                "telegram_set_commands_failed",
                user_id=user.telegram_id,
                error=str(exc),
            )


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
