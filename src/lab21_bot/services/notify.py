from __future__ import annotations

from typing import Any

import httpx
import structlog

logger = structlog.get_logger(__name__)

TELEGRAM_API = "https://api.telegram.org"


async def notify_telegram_user(bot_token: str, telegram_id: int, text: str) -> None:
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{TELEGRAM_API}/bot{bot_token}/sendMessage",
                json={"chat_id": telegram_id, "text": text},
                timeout=20.0,
            )
            payload: dict[str, Any] = response.json()
            if not payload.get("ok"):
                logger.info(
                    "telegram_notify_failed",
                    user_id=telegram_id,
                    error=payload.get("description"),
                )
    except Exception as exc:
        logger.info("telegram_notify_failed", user_id=telegram_id, error=str(exc))
