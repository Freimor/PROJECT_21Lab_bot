from __future__ import annotations

from lab21_bot.config import Settings


def miniapp_url(settings: Settings, fragment: str = "") -> str:
    base = settings.miniapp_base_url.rstrip("/")
    if fragment and not fragment.startswith("#"):
        fragment = f"#{fragment.lstrip('/')}"
    return f"{base}{fragment}"


def miniapp_deeplink(settings: Settings, fragment: str) -> str:
    return miniapp_url(settings, fragment)
