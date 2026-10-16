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
    assert body["bowed_today"] is False


@pytest.mark.asyncio
async def test_miniapp_shop_order_survives_telegram_failure(
    miniapp_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    from contextlib import asynccontextmanager

    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy.pool import StaticPool

    from lab21_bot.models import StaffRole, User
    from lab21_bot.services.store import create_product

    class _BrokenBot:
        async def __aenter__(self) -> _BrokenBot:
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

        async def send_message(self, *_args: object, **_kwargs: object) -> None:
            raise RuntimeError("telegram down")

        async def send_photo(self, *_args: object, **_kwargs: object) -> None:
            raise RuntimeError("telegram down")

        async def edit_message_text(self, *_args: object, **_kwargs: object) -> None:
            raise RuntimeError("telegram down")

        async def edit_message_caption(self, *_args: object, **_kwargs: object) -> None:
            raise RuntimeError("telegram down")

        async def delete_message(self, *_args: object, **_kwargs: object) -> None:
            return None

    monkeypatch.setattr(
        "lab21_bot.miniapp.routes.shop.create_bot", lambda _settings: _BrokenBot()
    )
    miniapp_settings.shop_thread_id = 7

    app = create_app(miniapp_settings)
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    factory = create_session_factory(engine)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    await bootstrap_database(engine, factory, miniapp_settings)
    app.state.engine = engine
    app.state.session_factory = factory
    app.state.settings = miniapp_settings

    @asynccontextmanager
    async def _keep_state(_app: object):
        yield

    app.router.lifespan_context = _keep_state

    async with factory() as session:
        buyer = User(
            telegram_id=999001,
            full_name="Mini",
            is_approved=True,
            balance=115,
        )
        session.add(buyer)
        lord = await session.get(User, miniapp_settings.bootstrap_magister_id)
        assert lord is not None
        assert lord.staff_role is StaffRole.LORD
        product = await create_product(
            session,
            lord,
            article="JIG",
            name="Дрифтовая жига",
            description="Жига за благодать",
            price=50,
            stock=3,
        )
        await session.commit()
        product_id = product.id

    headers = _auth_header(miniapp_settings.telegram_bot_token.get_secret_value())
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/miniapp/shop/orders",
            headers=headers,
            json={"product_id": product_id, "quantity": 1},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["product_id"] == product_id
        assert body["total_price"] == 50
        history = await client.get("/api/miniapp/history", headers=headers)
        assert history.status_code == 200, history.text
        entries = history.json()["entries"]
        assert entries[0]["delta"] == -50
        assert entries[0]["type"]

    async with factory() as session:
        from sqlalchemy import select

        from lab21_bot.models import LedgerEntry

        saved = await session.get(User, 999001)
        assert saved is not None
        assert saved.balance == 65
        ledger = await session.scalar(
            select(LedgerEntry).where(LedgerEntry.account_user_id == 999001)
        )
        assert ledger is not None
        assert len(ledger.transaction_group) <= 36
    await engine.dispose()


@pytest.mark.asyncio
async def test_miniapp_faq_list(miniapp_settings: Settings) -> None:
    headers = _auth_header(miniapp_settings.telegram_bot_token.get_secret_value())
    client = await _client_for(miniapp_settings)
    async with client:
        response = await client.get("/api/miniapp/faq", headers=headers)
    assert response.status_code == 200
    assert "pages" in response.json()


@pytest.mark.asyncio
async def test_member_quests_market_and_staff_gate(miniapp_settings: Settings) -> None:
    from lab21_bot.models import CommunityQuest, User

    app = create_app(miniapp_settings)
    engine = create_engine(miniapp_settings)
    factory = create_session_factory(engine)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    await bootstrap_database(engine, factory, miniapp_settings)
    app.state.engine = engine
    app.state.session_factory = factory
    app.state.settings = miniapp_settings
    headers = _auth_header(miniapp_settings.telegram_bot_token.get_secret_value())
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        created = await client.get("/api/miniapp/me", headers=headers)
        assert created.status_code == 200, created.text
        async with factory() as session:
            user = await session.get(User, 999001)
            assert user is not None
            user.is_approved = True
            user.rank = "adept"
            session.add(
                CommunityQuest(
                    number=7,
                    title="Стенд",
                    description="Собрать",
                    grace_reward=20,
                    respect_reward=4,
                    required_participants=3,
                    created_by=user.telegram_id,
                )
            )
            await session.commit()

        quests = await client.get("/api/miniapp/quests", headers=headers)
        assert quests.status_code == 200, quests.text
        item = quests.json()["quests"][0]
        assert item["title"] == "Стенд"
        assert item["reward"] == 20
        assert item["respect_reward"] == 4
        assert item["member_limit"] == 3
        assert item["joined"] is False

        market = await client.get("/api/miniapp/market/listings", headers=headers)
        assert market.status_code == 200, market.text
        assert market.json()["listings"] == []
        meta = await client.get("/api/miniapp/market/meta", headers=headers)
        assert meta.status_code == 200, meta.text
        assert meta.json()["categories"]

        staff = await client.get("/api/miniapp/staff/dashboard", headers=headers)
        assert staff.status_code == 403, staff.text
        queue = await client.get("/api/miniapp/staff/content/queue", headers=headers)
        assert queue.status_code == 403, queue.text

        me = await client.get("/api/miniapp/me", headers=headers)
        assert me.status_code == 200, me.text
        assert me.json()["rank"] == "adept"
        assert me.json()["rank_label"] == "Адепт"
    await engine.dispose()
