"""Telegram Bot API transport with optional multi-proxy failover."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import httpx
import structlog
from aiogram import Bot
from aiogram.client.session.aiohttp import AiohttpSession

from lab21_bot.config import Settings, get_settings

logger = structlog.get_logger(__name__)

TELEGRAM_API = "https://api.telegram.org"

_preferred_proxy: str | None = None


def proxy_urls(settings: Settings | None = None) -> list[str]:
    cfg = settings or get_settings()
    items: list[str] = []
    if cfg.telegram_proxy:
        items.append(cfg.telegram_proxy.strip())
    if cfg.telegram_proxies.strip():
        items.extend(part.strip() for part in cfg.telegram_proxies.split(",") if part.strip())
    seen: set[str] = set()
    ordered: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            ordered.append(item)
    return ordered


def _candidate_proxies(settings: Settings | None = None) -> list[str | None]:
    """Prefer last working proxy, then the rest. Empty list → direct connection."""
    proxies = proxy_urls(settings)
    if not proxies:
        return [None]
    ordered: list[str | None] = []
    if _preferred_proxy in proxies:
        ordered.append(_preferred_proxy)
    for proxy in proxies:
        if proxy != _preferred_proxy:
            ordered.append(proxy)
    return ordered


def remember_proxy(proxy: str | None) -> None:
    global _preferred_proxy
    _preferred_proxy = proxy


async def probe_proxy(
    proxy: str | None,
    bot_token: str,
    *,
    request_timeout: float = 15.0,
) -> bool:
    try:
        async with httpx.AsyncClient(proxy=proxy, timeout=request_timeout) as client:
            response = await client.get(f"{TELEGRAM_API}/bot{bot_token}/getMe")
            payload = response.json()
            return bool(payload.get("ok"))
    except Exception as exc:
        logger.info("telegram_proxy_probe_failed", proxy=_mask(proxy), error=str(exc))
        return False


async def select_proxy(settings: Settings) -> str | None:
    token = settings.telegram_bot_token.get_secret_value()
    candidates = _candidate_proxies(settings)
    for proxy in candidates:
        if await probe_proxy(proxy, token):
            remember_proxy(proxy)
            mode = "direct" if proxy is None else "proxy"
            logger.info("telegram_proxy_selected", proxy=_mask(proxy), mode=mode)
            return proxy
    if candidates == [None]:
        logger.warning("telegram_proxy_none_configured")
        return None
    logger.error("telegram_proxy_all_failed", count=len(candidates))
    # Keep first configured proxy so Bot still starts; requests may recover later.
    fallback = candidates[0]
    remember_proxy(fallback)
    return fallback


def create_bot(settings: Settings, *, proxy: str | None = None) -> Bot:
    """Build aiogram Bot using an explicit proxy, or preferred/first from settings."""
    token = settings.telegram_bot_token.get_secret_value()
    chosen = proxy
    if chosen is None:
        proxies = proxy_urls(settings)
        if _preferred_proxy in proxies:
            chosen = _preferred_proxy
        elif proxies:
            chosen = proxies[0]
    session = AiohttpSession(proxy=chosen) if chosen else AiohttpSession()
    return Bot(token=token, session=session)


async def create_bot_with_failover(settings: Settings) -> Bot:
    await select_proxy(settings)
    return create_bot(settings)


@asynccontextmanager
async def telegram_httpx(
    *,
    request_timeout: float = 30.0,
    settings: Settings | None = None,
) -> AsyncIterator[httpx.AsyncClient]:
    """Yield httpx client on the preferred proxy (no multi-try)."""
    cfg = settings or get_settings()
    proxy = _preferred_proxy
    proxies = proxy_urls(cfg)
    if proxy not in proxies and proxies:
        proxy = proxies[0]
    elif not proxies:
        proxy = None
    async with httpx.AsyncClient(proxy=proxy, timeout=request_timeout) as client:
        yield client


async def telegram_request(
    method: str,
    url: str,
    *,
    settings: Settings | None = None,
    request_timeout: float = 30.0,
    **kwargs: Any,
) -> httpx.Response:
    """HTTP request to Telegram API with proxy failover on transport errors."""
    cfg = settings or get_settings()
    errors: list[str] = []
    for proxy in _candidate_proxies(cfg):
        try:
            async with httpx.AsyncClient(proxy=proxy, timeout=request_timeout) as client:
                response = await getattr(client, method.lower())(url, **kwargs)
            remember_proxy(proxy)
            return response
        except (httpx.TransportError, httpx.TimeoutException) as exc:
            errors.append(f"{_mask(proxy)}: {exc}")
            logger.info("telegram_http_failover", proxy=_mask(proxy), error=str(exc))
            continue
    raise httpx.TransportError("; ".join(errors) or "all telegram proxies failed")


async def telegram_api_post(
    bot_token: str,
    api_method: str,
    payload: dict[str, Any] | None = None,
    *,
    request_timeout: float = 30.0,
    settings: Settings | None = None,
) -> dict[str, Any]:
    response = await telegram_request(
        "post",
        f"{TELEGRAM_API}/bot{bot_token}/{api_method}",
        settings=settings,
        request_timeout=request_timeout,
        json=payload or {},
    )
    data: dict[str, Any] = response.json()
    return data


async def telegram_api_get(
    bot_token: str,
    api_method: str,
    *,
    params: dict[str, Any] | None = None,
    request_timeout: float = 20.0,
    settings: Settings | None = None,
) -> httpx.Response:
    return await telegram_request(
        "get",
        f"{TELEGRAM_API}/bot{bot_token}/{api_method}",
        settings=settings,
        request_timeout=request_timeout,
        params=params,
    )


def _mask(proxy: str | None) -> str:
    if proxy is None:
        return "direct"
    if "@" in proxy:
        scheme, rest = proxy.split("://", 1) if "://" in proxy else ("", proxy)
        _creds, host = rest.rsplit("@", 1)
        return f"{scheme}://***@{host}" if scheme else f"***@{host}"
    return proxy
