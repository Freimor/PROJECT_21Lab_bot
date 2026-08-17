from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from lab21_bot.data import setting_default
from lab21_bot.models import ContentItem, TemplateKind, User
from lab21_bot.services.destinations import Destination
from lab21_bot.services.notify import send_telegram_message
from lab21_bot.services.settings import get_int_setting
from lab21_bot.services.templates import pick_template, render_template


def lab_post_link(
    channel_id: int | None,
    message_id: int | None,
    *,
    thread_id: int | None = None,
) -> str:
    if not channel_id or not message_id:
        return ""
    raw = str(channel_id)
    if not raw.startswith("-100"):
        return ""
    chat = raw[4:]
    if thread_id is not None:
        return f"https://t.me/c/{chat}/{thread_id}/{message_id}"
    return f"https://t.me/c/{chat}/{message_id}"


async def maybe_send_flood_teaser(
    session: AsyncSession,
    bot_token: str,
    flood: Destination | None,
    item: ContentItem,
    author: User | None,
    *,
    story_thread_id: int | None = None,
) -> None:
    if flood is None or author is None:
        return
    if item.kind.value != "story":
        return
    if not await get_int_setting(
        session, "teasers_enabled", setting_default("teasers_enabled")
    ):
        return
    template = await pick_template(session, TemplateKind.FLOOD_TEASER)
    if template is None:
        return
    text = render_template(
        template.body,
        name=author.full_name,
        username=author.username or "user",
        link=lab_post_link(
            item.published_channel_id,
            item.published_message_id,
            thread_id=story_thread_id,
        ),
    )
    await send_telegram_message(
        bot_token,
        flood.chat_id,
        text,
        message_thread_id=flood.thread_id,
    )
