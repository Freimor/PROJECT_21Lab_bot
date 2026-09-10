from __future__ import annotations

import hashlib
import hmac
import time
from urllib.parse import urlencode

import pytest
from httpx import ASGITransport, AsyncClient

from lab21_bot.admin.app import create_app
from lab21_bot.config import Settings
from lab21_bot.db import bootstrap_database, create_engine, create_session_factory
from lab21_bot.models import Base


async def _client_for(settings: Settings) -> AsyncClient:
    app = create_app(settings)
    engine = create_engine(settings)
    factory = create_session_factory(engine)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    await bootstrap_database(engine, factory, settings)
    app.state.engine = engine
    app.state.session_factory = factory
    app.state.settings = settings
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


def _sign(parsed: dict[str, str], bot_token: str) -> str:
    data_check = "\n".join(f"{k}={v}" for k, v in sorted(parsed.items()))
    secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    return hmac.new(secret, data_check.encode(), hashlib.sha256).hexdigest()


from lab21_bot.miniapp.auth import validate_init_data


def _auth_header(bot_token: str, user_id: int = 999001) -> dict[str, str]:
    from tests.test_miniapp_auth import _make_init_data

    init_data = _make_init_data(bot_token, user=f'{{"id":{user_id},"first_name":"Mini","username":"mini"}}')
    assert validate_init_data(init_data, bot_token)
    return {"Authorization": f"tma {init_data}"}


@pytest.fixture
def miniapp_settings(monkeypatch: pytest.MonkeyPatch) -> Settings:
    from lab21_bot.config import get_settings

    get_settings.cache_clear()
    settings = Settings(
        telegram_bot_token="999:TESTTOKEN",
        bootstrap_magister_id=1,
        main_channel_id=-1001,
        staff_chat_id=-1002,
        database_url="sqlite+aiosqlite:///:memory:",
        miniapp_enabled=True,
        miniapp_base_url="http://test/app",
        admin_enabled=True,
    )
    monkeypatch.setattr("lab21_bot.config.get_settings", lambda: settings)
    monkeypatch.setattr("lab21_bot.miniapp.deps.get_settings", lambda: settings)
    return settings


@pytest.mark.asyncio
async def test_miniapp_me_unauthorized(miniapp_settings: Settings) -> None:
    client = await _client_for(miniapp_settings)
    async with client:
        response = await client.get("/api/miniapp/me")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_miniapp_me_creates_user(miniapp_settings: Settings) -> None:
    headers = _auth_header(miniapp_settings.telegram_bot_token.get_secret_value())
    client = await _client_for(miniapp_settings)
    async with client:
        response = await client.get("/api/miniapp/me", headers=headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["telegram_id"] == 999001
    assert body["registered"] is True


@pytest.mark.asyncio
async def test_miniapp_faq_list(miniapp_settings: Settings) -> None:
    headers = _auth_header(miniapp_settings.telegram_bot_token.get_secret_value())
    client = await _client_for(miniapp_settings)
    async with client:
        response = await client.get("/api/miniapp/faq", headers=headers)
    assert response.status_code == 200
    assert "pages" in response.json()
