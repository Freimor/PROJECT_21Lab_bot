from __future__ import annotations

import re

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr

from lab21_bot.admin.app import create_app
from lab21_bot.admin.auth import reset_otp_cooldowns
from lab21_bot.admin.deps import get_settings
from lab21_bot.config import Settings
from lab21_bot.db import bootstrap_database, create_engine, create_session_factory
from lab21_bot.models import Base, User


def _settings() -> Settings:
    return Settings(
        telegram_bot_token=SecretStr("999:TESTTOKEN"),
        bootstrap_magister_id=42,
        main_channel_id=-1001,
        staff_chat_id=-1002,
        database_url="sqlite+aiosqlite:///:memory:",
        admin_base_url="https://lab21.microelectronics.dev",
        telegram_bot_username="lab21bot",
    )


async def _client(settings: Settings) -> AsyncClient:
    app = create_app(settings)
    app.dependency_overrides[get_settings] = lambda: settings
    engine = create_engine(settings)
    factory = create_session_factory(engine)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    await bootstrap_database(engine, factory, settings)
    async with factory() as session:
        user = await session.get(User, 42)
        assert user is not None
        user.username = "lord"
        await session.commit()
    app.state.engine = engine
    app.state.session_factory = factory
    app.state.settings = settings
    transport = ASGITransport(app=app)
    return AsyncClient(
        transport=transport,
        base_url="https://lab21.microelectronics.dev",
        follow_redirects=True,
    )


@pytest.mark.asyncio
async def test_staff_login_code_roundtrip(monkeypatch: pytest.MonkeyPatch) -> None:
    reset_otp_cooldowns()
    sent: list[tuple[int, str]] = []

    async def fake_send(_token: str, chat_id: int, text: str, **_kwargs: object) -> int:
        sent.append((chat_id, text))
        return 1

    monkeypatch.setattr("lab21_bot.admin.routes.auth.send_telegram_message", fake_send)
    settings = _settings()
    client = await _client(settings)
    async with client:
        asked = await client.post("/auth/code/request", data={"identity": "@lord"})
        assert asked.status_code == 200
        assert "Код из Telegram" in asked.text
        assert sent and sent[0][0] == 42
        match = re.search(r"Код входа в админку Lab21: (\d{6})", sent[0][1])
        assert match is not None
        logged_in = await client.post(
            "/auth/code",
            data={"code": match.group(1)},
            follow_redirects=False,
        )
    assert logged_in.status_code == 303
    assert logged_in.headers["location"] == "/"
    reset_otp_cooldowns()


@pytest.mark.asyncio
async def test_unknown_user_does_not_send_code(monkeypatch: pytest.MonkeyPatch) -> None:
    reset_otp_cooldowns()
    sent: list[int] = []

    async def fake_send(_token: str, chat_id: int, text: str, **_kwargs: object) -> int:
        sent.append(chat_id)
        return 1

    monkeypatch.setattr("lab21_bot.admin.routes.auth.send_telegram_message", fake_send)
    client = await _client(_settings())
    async with client:
        asked = await client.post("/auth/code/request", data={"identity": "nobody"})
    assert asked.status_code == 200
    assert "Код из Telegram" in asked.text
    assert sent == []
    reset_otp_cooldowns()
