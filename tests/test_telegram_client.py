from __future__ import annotations

import httpx
import pytest
from pydantic import SecretStr

from lab21_bot import telegram_client as tc
from lab21_bot.config import Settings


def _settings(**kwargs: object) -> Settings:
    base = dict(
        telegram_bot_token=SecretStr("1:test"),
        bootstrap_magister_id=1,
        database_url="sqlite+aiosqlite:///:memory:",
        main_channel_id=-1001,
        staff_chat_id=-1002,
    )
    base.update(kwargs)
    return Settings(**base)  # type: ignore[arg-type]


def test_proxy_urls_merge_and_dedupe() -> None:
    settings = _settings(
        telegram_proxy="socks5://a:1080",
        telegram_proxies="socks5://b:1080, socks5://a:1080, socks5://c:1080",
    )
    assert tc.proxy_urls(settings) == [
        "socks5://a:1080",
        "socks5://b:1080",
        "socks5://c:1080",
    ]


def test_candidate_order_prefers_remembered(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _settings(telegram_proxies="socks5://a:1080,socks5://b:1080")
    monkeypatch.setattr(tc, "_preferred_proxy", "socks5://b:1080")
    assert tc._candidate_proxies(settings) == ["socks5://b:1080", "socks5://a:1080"]


@pytest.mark.asyncio
async def test_telegram_request_failovers(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _settings(telegram_proxies="socks5://bad:1080,socks5://good:1080")
    monkeypatch.setattr(tc, "_preferred_proxy", None)
    calls: list[str | None] = []

    class FakeClient:
        def __init__(
            self,
            proxy: str | None = None,
            timeout: float | None = None,
        ) -> None:
            self.proxy = proxy

        async def __aenter__(self) -> FakeClient:
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def get(self, url: str, **kwargs: object) -> httpx.Response:
            calls.append(self.proxy)
            if self.proxy == "socks5://bad:1080":
                raise httpx.ConnectError("blocked")
            return httpx.Response(200, json={"ok": True}, request=httpx.Request("GET", url))

    monkeypatch.setattr(tc.httpx, "AsyncClient", FakeClient)
    url = "https://api.telegram.org/bot1:test/getMe"
    response = await tc.telegram_request("get", url, settings=settings)
    assert response.status_code == 200
    assert calls == ["socks5://bad:1080", "socks5://good:1080"]
    assert tc._preferred_proxy == "socks5://good:1080"
