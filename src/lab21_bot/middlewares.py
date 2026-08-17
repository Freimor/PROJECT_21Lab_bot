"""Aiogram middlewares for chat hygiene."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject

from lab21_bot.services.chat_ui import delete_quietly

# These commands *are* the user-facing post (intake + reaction). Do not delete them.
_KEEP_COMMANDS = frozenset({"/bug", "/upgrade"})


def leading_bot_command(message: Message) -> str | None:
    entities = message.entities or []
    if not entities or entities[0].type != "bot_command" or entities[0].offset != 0:
        return None
    text = message.text or ""
    raw = text[: entities[0].length]
    return raw.split("@", 1)[0].lower()


def should_delete_command_message(message: Message) -> bool:
    token = leading_bot_command(message)
    return token is not None and token not in _KEEP_COMMANDS


class DeleteCommandMessageMiddleware(BaseMiddleware):
    """Remove the user's slash-command message before the handler runs."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if isinstance(event, Message) and should_delete_command_message(event):
            await delete_quietly(event)
        return await handler(event, data)
