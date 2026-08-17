"""Telegram chat/topic destinations for publications."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from lab21_bot.models import ContentKind


class DestinationError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class Destination:
    chat_id: int
    thread_id: int | None = None


def destination_for_kind(settings: Any, kind: ContentKind) -> Destination:
    if kind is ContentKind.IMPORTANT:
        if settings.important_channel_id is None and settings.important_thread_id is None:
            raise DestinationError("IMPORTANT_CHANNEL_ID или IMPORTANT_THREAD_ID не задан")
        return Destination(
            int(settings.important_channel_id or settings.main_channel_id),
            settings.important_thread_id,
        )
    if kind is ContentKind.MEME:
        flood = flood_destination(settings)
        if flood is None:
            raise DestinationError("FLOOD_CHAT_ID или FLOOD_THREAD_ID не задан")
        return flood
    return Destination(int(settings.main_channel_id), settings.main_thread_id)


def flood_destination(settings: Any) -> Destination | None:
    if settings.flood_chat_id is None and settings.flood_thread_id is None:
        return None
    return Destination(
        int(settings.flood_chat_id or settings.main_channel_id),
        settings.flood_thread_id,
    )


def job_destination(settings: Any) -> Destination | None:
    job_chat = getattr(settings, "resolved_job_chat_id", None)
    if job_chat is None:
        job_chat = getattr(settings, "job_chat_id", None) or getattr(
            settings, "job_channel_id", None
        )
    job_thread = getattr(settings, "job_thread_id", None)
    if job_chat is None and job_thread is None:
        return None
    return Destination(
        int(job_chat or settings.main_channel_id),
        job_thread,
    )


def shop_destination(settings: Any) -> Destination | None:
    shop_chat = getattr(settings, "shop_chat_id", None)
    shop_thread = getattr(settings, "shop_thread_id", None)
    if shop_chat is None and shop_thread is None:
        return None
    return Destination(
        int(shop_chat or settings.main_channel_id),
        shop_thread,
    )


def bugs_destination(settings: Any) -> Destination | None:
    """Source topic/chat where users post /bug and /upgrade."""
    bugs_chat = getattr(settings, "bugs_chat_id", None)
    bugs_thread = getattr(settings, "bugs_thread_id", None)
    if bugs_chat is None and bugs_thread is None:
        return None
    return Destination(
        int(bugs_chat or settings.main_channel_id),
        bugs_thread,
    )


def matches_bugs_destination(
    settings: Any,
    *,
    chat_id: int,
    thread_id: int | None,
) -> bool:
    dest = bugs_destination(settings)
    if dest is None:
        return False
    if chat_id != dest.chat_id:
        return False
    if dest.thread_id is None:
        return True
    return thread_id == dest.thread_id


def matches_shop_destination(
    settings: Any,
    *,
    chat_id: int,
    thread_id: int | None,
) -> bool:
    dest = shop_destination(settings)
    if dest is None:
        return False
    if chat_id != dest.chat_id:
        return False
    if dest.thread_id is None:
        return True
    return thread_id == dest.thread_id


def matches_destination(
    settings: Any,
    *,
    chat_id: int,
    thread_id: int | None,
    kind: ContentKind,
) -> bool:
    try:
        dest = destination_for_kind(settings, kind)
    except DestinationError:
        return False
    if chat_id != dest.chat_id:
        return False
    if dest.thread_id is None:
        return True
    return thread_id == dest.thread_id
