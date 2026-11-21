from __future__ import annotations

from typing import Any

import pytest

from lab21_bot import main as main_mod


@pytest.mark.asyncio
async def test_run_polling_with_proxy_failover(monkeypatch: pytest.MonkeyPatch) -> None:
    class ProxyConnectionError(Exception):
        pass

    bots: list[Any] = ["bot-1", "bot-2"]
    holder = {"bot": bots[0], "idx": 0}
    events: list[str] = []

    class FakeDispatcher:
        async def start_polling(self, bot: object) -> None:
            events.append(f"poll:{bot}")
            if bot == "bot-1":
                raise ProxyConnectionError("proxy dead")
            return None

    async def fake_create(_settings: object) -> str:
        holder["idx"] += 1
        return bots[holder["idx"]]

    async def fake_sleep(*_args: object, **_kwargs: object) -> None:
        return None

    monkeypatch.setattr(main_mod, "create_bot_with_failover", fake_create)
    monkeypatch.setattr(main_mod, "is_telegram_transport_error", lambda exc: True)
    monkeypatch.setattr(main_mod.asyncio, "sleep", fake_sleep)

    logs: list[str] = []

    class Log:
        def warning(self, event: str, **kwargs: object) -> None:
            logs.append(event)

    await main_mod.run_polling_with_proxy_failover(
        FakeDispatcher(),  # type: ignore[arg-type]
        object(),  # type: ignore[arg-type]
        lambda: holder["bot"],
        lambda bot: holder.__setitem__("bot", bot),
        Log(),
    )
    assert events == ["poll:bot-1", "poll:bot-2"]
    assert logs == ["polling_proxy_failover"]
    assert holder["bot"] == "bot-2"
