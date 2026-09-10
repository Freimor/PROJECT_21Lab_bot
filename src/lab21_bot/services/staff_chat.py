"""Staff chat membership via Telegram Bot API.

Bots cannot force-add users into a group; we create a one-time invite link.
Removal uses ban+unban (kick without permanent ban).
"""

from __future__ import annotations

from typing import Any

import structlog

from lab21_bot.data import phrase
from lab21_bot.telegram_client import telegram_api_post

logger = structlog.get_logger(__name__)


async def _post(bot_token: str, method: str, payload: dict[str, Any]) -> dict[str, Any]:
    return await telegram_api_post(bot_token, method, payload, request_timeout=30.0)


async def create_staff_invite_link(
    bot_token: str,
    staff_chat_id: int,
    *,
    user_id: int,
) -> str | None:
    """Create a single-use invite link for the staff chat."""
    payload = await _post(
        bot_token,
        "createChatInviteLink",
        {
            "chat_id": staff_chat_id,
            "name": f"staff-{user_id}"[:32],
            "member_limit": 1,
        },
    )
    if not payload.get("ok"):
        logger.info(
            "staff_invite_failed",
            user_id=user_id,
            chat_id=staff_chat_id,
            error=payload.get("description"),
        )
        return None
    result = payload.get("result") or {}
    link = result.get("invite_link")
    return str(link) if link else None


async def invite_to_staff_chat(
    bot_token: str,
    staff_chat_id: int,
    user_id: int,
) -> str | None:
    """Send a one-time staff-chat invite to the user. Returns the link if created."""
    link = await create_staff_invite_link(bot_token, staff_chat_id, user_id=user_id)
    if link is None:
        return None
    text = phrase("application", "staff_chat_invite", link=link)
    notify = await _post(
        bot_token,
        "sendMessage",
        {"chat_id": user_id, "text": text, "disable_web_page_preview": True},
    )
    if not notify.get("ok"):
        logger.info(
            "staff_invite_notify_failed",
            user_id=user_id,
            error=notify.get("description"),
        )
    return link


async def kick_from_staff_chat(
    bot_token: str,
    staff_chat_id: int,
    user_id: int,
) -> bool:
    """Remove user from staff chat (ban then unban so they can rejoin later)."""
    ban = await _post(
        bot_token,
        "banChatMember",
        {"chat_id": staff_chat_id, "user_id": user_id},
    )
    if not ban.get("ok"):
        logger.info(
            "staff_kick_ban_failed",
            user_id=user_id,
            chat_id=staff_chat_id,
            error=ban.get("description"),
        )
        # Still try unban in case they were already banned / not a member
    unban = await _post(
        bot_token,
        "unbanChatMember",
        {"chat_id": staff_chat_id, "user_id": user_id, "only_if_banned": False},
    )
    if not unban.get("ok"):
        logger.info(
            "staff_kick_unban_failed",
            user_id=user_id,
            chat_id=staff_chat_id,
            error=unban.get("description"),
        )
        return bool(ban.get("ok"))
    return True
