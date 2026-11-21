from __future__ import annotations

import asyncio
import os
import sys

from sqlalchemy import text

from lab21_bot.config import get_settings
from lab21_bot.db import create_engine


def _truthy(raw: str | None) -> bool:
    return (raw or "").strip().lower() in {"1", "true", "yes", "on"}


async def check() -> None:
    settings = get_settings()
    engine = create_engine(settings)
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
    finally:
        await engine.dispose()

    if not _truthy(os.environ.get("HEALTH_CHECK_TELEGRAM")):
        return

    from lab21_bot.telegram_client import _candidate_proxies, probe_proxy

    token = settings.telegram_bot_token.get_secret_value()
    for proxy in _candidate_proxies(settings):
        if await probe_proxy(proxy, token, request_timeout=10.0):
            return
    print("telegram health probe failed", file=sys.stderr)
    raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(check())
