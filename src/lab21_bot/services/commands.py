from __future__ import annotations

from typing import Any

import httpx
import structlog
from aiogram import Bot
from aiogram.types import BotCommand, BotCommandScopeChat, BotCommandScopeDefault

from lab21_bot.models import User
from lab21_bot.services.access import Permission, has_permission

logger = structlog.get_logger(__name__)
TELEGRAM_API = "https://api.telegram.org"


def commands_for_user(user: User) -> list[BotCommand]:
    if not user.is_approved:
        return []
    if user.staff_role is not None:
        commands = [
            BotCommand(command="menu", description="Главное меню"),
            BotCommand(command="staff", description="Служебное меню"),
        ]
        if has_permission(user, Permission.CREATE_STAFF_CONTENT):
            commands.append(BotCommand(command="post", description="Создать пост"))
        if has_permission(user, Permission.MANAGE_ECONOMY):
            commands.extend(
                [
                    BotCommand(command="grant", description="Начислить 🙏"),
                    BotCommand(command="withdraw", description="Списать 🙏"),
                    BotCommand(command="respect_grant", description="Начислить ❇"),
                    BotCommand(
                        command="respect_withdraw", description="Списать ❇"
                    ),
                ]
            )
        if has_permission(user, Permission.MANAGE_STORE):
            commands.extend(
                [
                    BotCommand(command="product", description="Создать товар"),
                    BotCommand(command="product_edit", description="Изменить товар"),
                ]
            )
        if has_permission(user, Permission.MANAGE_SETTINGS):
            commands.append(BotCommand(command="setting", description="Изменить настройку"))
        if has_permission(user, Permission.MANAGE_SYSTEM):
            commands.extend(
                [
                    BotCommand(command="reboot", description="Перезагрузка"),
                    BotCommand(command="update_status", description="Проверить обновления"),
                ]
            )
        return commands
    return [
        BotCommand(command="menu", description="Главное меню"),
        BotCommand(command="balance", description="Ранг, 🙏 и ❇"),
        BotCommand(command="history", description="История 🙏"),
        BotCommand(command="order", description="Заказать услугу"),
        BotCommand(command="transfer", description="Передать 🙏"),
    ]


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
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{TELEGRAM_API}/bot{bot_token}/setMyCommands",
                json=payload,
                timeout=20.0,
            )
            body: dict[str, Any] = response.json()
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
