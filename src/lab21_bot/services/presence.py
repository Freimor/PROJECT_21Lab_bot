"""In-memory cooldowns and mention reply helpers."""

from __future__ import annotations

import random
import time
from typing import Any

from aiogram.types import Message, MessageEntity

from lab21_bot.data import phrase_choices, random_phrase


_cooldowns: dict[str, float] = {}


def cooldown_remaining(key: str) -> float:
    until = _cooldowns.get(key, 0.0)
    return max(0.0, until - time.monotonic())


def set_cooldown(key: str, seconds: float) -> None:
    _cooldowns[key] = time.monotonic() + max(0.0, seconds)


def message_mentions_bot(
    message: Message,
    *,
    bot_id: int,
    bot_username: str | None,
) -> bool:
    if message.from_user and message.from_user.is_bot:
        return False
    reply = message.reply_to_message
    if reply is not None and reply.from_user is not None and reply.from_user.id == bot_id:
        return True
    entities = list(message.entities or []) + list(message.caption_entities or [])
    text = message.text or message.caption or ""
    username = (bot_username or "").lstrip("@").lower()
    for entity in entities:
        if _entity_mentions_bot(entity, text, bot_id=bot_id, bot_username=username):
            return True
    return False


def _entity_mentions_bot(
    entity: MessageEntity,
    text: str,
    *,
    bot_id: int,
    bot_username: str,
) -> bool:
    if entity.type == "mention" and bot_username:
        chunk = text[entity.offset : entity.offset + entity.length]
        return chunk.lstrip("@").lower() == bot_username
    if entity.type == "text_mention" and entity.user is not None:
        return entity.user.id == bot_id
    return False


def pick_mention_reply(*, phrases_key: str | None = None) -> str:
    if phrases_key:
        seasonal = phrase_choices("presence", "seasons", phrases_key)
        if seasonal:
            return random.choice(seasonal)
    return random_phrase("presence", "mention_replies")


def clear_cooldowns_for_tests() -> None:
    _cooldowns.clear()
