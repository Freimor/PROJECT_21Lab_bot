from __future__ import annotations

from typing import Any

import httpx
import structlog

logger = structlog.get_logger(__name__)

TELEGRAM_API = "https://api.telegram.org"


async def notify_telegram_user(
    bot_token: str,
    telegram_id: int,
    text: str,
    *,
    parse_mode: str | None = None,
) -> None:
    try:
        payload: dict[str, Any] = {"chat_id": telegram_id, "text": text}
        if parse_mode:
            payload["parse_mode"] = parse_mode
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{TELEGRAM_API}/bot{bot_token}/sendMessage",
                json=payload,
                timeout=20.0,
            )
            result: dict[str, Any] = response.json()
            if not result.get("ok"):
                logger.info(
                    "telegram_notify_failed",
                    user_id=telegram_id,
                    error=result.get("description"),
                )
    except Exception as exc:
        logger.info("telegram_notify_failed", user_id=telegram_id, error=str(exc))


class TelegramSendError(RuntimeError):
    pass


def _thread_fields(message_thread_id: int | None) -> dict[str, int]:
    if message_thread_id is None:
        return {}
    return {"message_thread_id": message_thread_id}


def _parse_mode_fields(parse_mode: str | None) -> dict[str, str]:
    if not parse_mode:
        return {}
    return {"parse_mode": parse_mode}


async def send_telegram_message(
    bot_token: str,
    chat_id: int,
    text: str,
    *,
    media: list[dict[str, Any]] | None = None,
    message_thread_id: int | None = None,
    parse_mode: str | None = None,
) -> int:
    """Send text (and optional single media) to a chat/topic; return message_id."""
    thread = _thread_fields(message_thread_id)
    mode = _parse_mode_fields(parse_mode)
    async with httpx.AsyncClient(timeout=40.0) as client:
        items = media or []
        if not items:
            response = await client.post(
                f"{TELEGRAM_API}/bot{bot_token}/sendMessage",
                json={"chat_id": chat_id, "text": text, **thread, **mode},
            )
            payload = response.json()
            if not payload.get("ok"):
                raise TelegramSendError(str(payload.get("description", "send failed")))
            return int(payload["result"]["message_id"])

        first = items[0]
        caption = text if len(text) <= 1024 else None
        method = {
            "photo": "sendPhoto",
            "animation": "sendAnimation",
            "video": "sendVideo",
            "document": "sendDocument",
        }.get(first.get("type", ""), "sendDocument")
        field = {
            "sendPhoto": "photo",
            "sendAnimation": "animation",
            "sendVideo": "video",
            "sendDocument": "document",
        }[method]
        response = await client.post(
            f"{TELEGRAM_API}/bot{bot_token}/{method}",
            json={
                "chat_id": chat_id,
                field: first["file_id"],
                **thread,
                **({"caption": caption, **mode} if caption else {}),
            },
        )
        payload = response.json()
        if not payload.get("ok"):
            raise TelegramSendError(str(payload.get("description", "send failed")))
        message_id = int(payload["result"]["message_id"])
        if caption is None and text.strip():
            follow = await client.post(
                f"{TELEGRAM_API}/bot{bot_token}/sendMessage",
                json={"chat_id": chat_id, "text": text, **thread, **mode},
            )
            follow_payload = follow.json()
            if follow_payload.get("ok"):
                message_id = int(follow_payload["result"]["message_id"])
        return message_id
