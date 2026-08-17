from __future__ import annotations

from typing import Any, cast

import httpx
import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from lab21_bot.models import User

logger = structlog.get_logger(__name__)

TELEGRAM_API = "https://api.telegram.org"


class TelegramProfileError(RuntimeError):
    pass


async def _telegram_call(
    client: httpx.AsyncClient,
    bot_token: str,
    method: str,
    *,
    params: dict[str, Any] | None = None,
    timeout: float = 20.0,
) -> dict[str, Any]:
    try:
        response = await client.get(
            f"{TELEGRAM_API}/bot{bot_token}/{method}",
            params=params,
            timeout=timeout,
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise TelegramProfileError(f"Telegram недоступен: {exc}") from exc
    payload = response.json()
    if not payload.get("ok"):
        raise TelegramProfileError(str(payload.get("description", "Telegram API error")))
    return cast(dict[str, Any], payload["result"])


def _compose_full_name(chat: dict[str, Any]) -> str:
    first = (chat.get("first_name") or "").strip()
    last = (chat.get("last_name") or "").strip()
    name = f"{first} {last}".strip()
    if name:
        return name
    username = (chat.get("username") or "").strip()
    return username or "Участник"


async def fetch_avatar_file_id(
    client: httpx.AsyncClient,
    bot_token: str,
    telegram_id: int,
) -> str | None:
    photos = await _telegram_call(
        client,
        bot_token,
        "getUserProfilePhotos",
        params={"user_id": telegram_id, "limit": 1},
    )
    if int(photos.get("total_count") or 0) <= 0:
        return None
    sizes = photos["photos"][0]
    if not sizes:
        return None
    return str(sizes[-1]["file_id"])


async def sync_user_profile(
    session: AsyncSession,
    user: User,
    bot_token: str,
    *,
    client: httpx.AsyncClient | None = None,
) -> User:
    """Refresh username/full_name/avatar from Telegram Bot API.

    Requires that the user has previously opened a private chat with the bot
    (e.g. pressed /start). Otherwise Telegram returns chat-not-found.
    """
    owns_client = client is None
    http = client or httpx.AsyncClient()
    try:
        chat = await _telegram_call(
            http,
            bot_token,
            "getChat",
            params={"chat_id": user.telegram_id},
            timeout=5.0,
        )
        user.full_name = _compose_full_name(chat)
        username = chat.get("username")
        user.username = str(username) if username else None
        try:
            user.avatar_file_id = await fetch_avatar_file_id(http, bot_token, user.telegram_id)
        except TelegramProfileError as exc:
            logger.info("avatar_sync_skipped", user_id=user.telegram_id, error=str(exc))
        await session.flush()
        return user
    except TelegramProfileError as exc:
        logger.info("profile_sync_skipped", user_id=user.telegram_id, error=str(exc))
        return user
    finally:
        if owns_client:
            await http.aclose()


async def sync_users_profiles(
    session: AsyncSession,
    users: list[User],
    bot_token: str,
) -> None:
    async with httpx.AsyncClient() as client:
        for user in users:
            await sync_user_profile(session, user, bot_token, client=client)


async def download_telegram_file(
    bot_token: str,
    file_id: str,
) -> tuple[bytes, str]:
    async with httpx.AsyncClient() as client:
        file_info = await _telegram_call(
            client,
            bot_token,
            "getFile",
            params={"file_id": file_id},
        )
        file_path = file_info.get("file_path")
        if not file_path:
            raise TelegramProfileError("Файл аватара недоступен")
        response = await client.get(
            f"{TELEGRAM_API}/file/bot{bot_token}/{file_path}",
            timeout=30.0,
        )
        response.raise_for_status()
        content_type = response.headers.get("content-type", "image/jpeg")
        return response.content, content_type
