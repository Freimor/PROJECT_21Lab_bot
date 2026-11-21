from __future__ import annotations

import pytest
from pydantic import SecretStr

from lab21_bot import health as health_mod
from lab21_bot.config import Settings


def _settings() -> Settings:
    return Settings(  # type: ignore[arg-type]
        telegram_bot_token=SecretStr("1:test"),
        bootstrap_magister_id=1,
        database_url="sqlite+aiosqlite:///:memory:",
        main_channel_id=-1001,
        staff_chat_id=-1002,
    )


@pytest.mark.asyncio
async def test_health_db_only_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HEALTH_CHECK_TELEGRAM", raising=False)
    monkeypatch.setattr(health_mod, "get_settings", _settings)

    class FakeConn:
        async def execute(self, *_args: object, **_kwargs: object) -> None:
            return None

        async def __aenter__(self) -> FakeConn:
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

    class FakeEngine:
        def connect(self) -> FakeConn:
            return FakeConn()

        async def dispose(self) -> None:
            return None

    monkeypatch.setattr(health_mod, "create_engine", lambda _settings: FakeEngine())
    probed = {"called": False}

    async def boom(*_args: object, **_kwargs: object) -> bool:
        probed["called"] = True
        return False

    monkeypatch.setattr("lab21_bot.telegram_client.probe_proxy", boom)
    await health_mod.check()
    assert probed["called"] is False


@pytest.mark.asyncio
async def test_health_telegram_probe_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HEALTH_CHECK_TELEGRAM", "1")
    monkeypatch.setattr(health_mod, "get_settings", _settings)

    class FakeConn:
        async def execute(self, *_args: object, **_kwargs: object) -> None:
            return None

        async def __aenter__(self) -> FakeConn:
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

    class FakeEngine:
        def connect(self) -> FakeConn:
            return FakeConn()

        async def dispose(self) -> None:
            return None

    monkeypatch.setattr(health_mod, "create_engine", lambda _settings: FakeEngine())

    async def never(*_args: object, **_kwargs: object) -> bool:
        return False

    monkeypatch.setattr("lab21_bot.telegram_client.probe_proxy", never)
    monkeypatch.setattr(
        "lab21_bot.telegram_client._candidate_proxies",
        lambda _settings=None: [None],
    )
    with pytest.raises(SystemExit) as exc:
        await health_mod.check()
    assert exc.value.code == 1
