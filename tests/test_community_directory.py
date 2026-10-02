import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from lab21_bot.admin.app import create_app
from lab21_bot.admin.deps import get_settings, require_user
from lab21_bot.config import Settings
from lab21_bot.models import Base, CommunityRank, StaffRole, User
from lab21_bot.services.applications import search_community_directory
from lab21_bot.services.testuser import TEST_USER_ID


def _person(
    telegram_id: int,
    name: str,
    *,
    username: str | None = None,
    role: StaffRole | None = None,
    approved: bool = True,
    active: bool = True,
    skills: list[str] | None = None,
    rank: CommunityRank = CommunityRank.NOVICE,
) -> User:
    return User(
        telegram_id=telegram_id,
        full_name=name,
        username=username,
        staff_role=role,
        is_approved=approved,
        is_active=active,
        skill_ids=list(skills or []),
        rank=rank,
    )


async def test_directory_search_and_filters(session: AsyncSession) -> None:
    session.add_all(
        [
            _person(1, "Иван Петров", username="ivan", skills=["solder"]),
            _person(2, "Мария", username="maria", role=StaffRole.WATCHER),
            _person(3, "Гость", approved=False),
            _person(4, "Старый", active=False),
            _person(TEST_USER_ID, "Тестовый участник"),
        ]
    )
    await session.flush()

    names = [user.full_name for user in await search_community_directory(session)]
    assert names == ["Иван Петров", "Мария"]

    found = await search_community_directory(session, query="петр")
    assert [user.telegram_id for user in found] == [1]
    by_username = await search_community_directory(session, query="@maria")
    assert [user.telegram_id for user in by_username] == [2]
    staff = await search_community_directory(session, status="staff", role="watcher")
    assert [user.telegram_id for user in staff] == [2]
    skilled = await search_community_directory(session, skill="solder")
    assert [user.telegram_id for user in skilled] == [1]
    removed = await search_community_directory(session, status="removed")
    assert [user.telegram_id for user in removed] == [4]
    pending = await search_community_directory(session, status="pending")
    assert [user.telegram_id for user in pending] == [3]


def _settings(tmp_path) -> Settings:
    return Settings(
        telegram_bot_token=SecretStr("999:TESTTOKEN"),
        bootstrap_magister_id=42,
        main_channel_id=-1001,
        staff_chat_id=-1002,
        database_url="sqlite+aiosqlite:///:memory:",
        admin_base_url="http://test",
        upload_dir=str(tmp_path / "uploads"),
    )


async def test_community_pages_render(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    async def noop(*_args: object, **_kwargs: object) -> None:
        return None

    monkeypatch.setattr("lab21_bot.admin.routes.people.sync_users_profiles", noop)
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        lord = _person(7, "Лорд", role=StaffRole.LORD)
        member = _person(8, "Иван Петров", username="ivan", skills=["solder"])
        session.add_all([lord, member])
        await session.commit()

    settings = _settings(tmp_path)
    app = create_app(settings)
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[require_user] = lambda: _person(7, "Лорд", role=StaffRole.LORD)
    app.state.engine = engine
    app.state.session_factory = factory
    app.state.settings = settings
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        listing = await client.get("/community/members?q=петр")
        card = await client.get("/community/members/7")
        roles = await client.get("/community/roles")
        staff = await client.get("/community/staff", follow_redirects=False)
    await engine.dispose()

    assert listing.status_code == 200
    assert "Иван Петров" in listing.text
    assert "Мария" not in listing.text
    assert 'name="q"' in listing.text
    assert 'name="skill"' in listing.text
    assert "skill-line" in listing.text
    assert "data-skill" in listing.text
    assert card.status_code == 200
    assert "Разрешить /testuser" in card.text
    assert "Сохранить должность" in card.text
    assert roles.status_code == 200
    assert "Добавить роль" in roles.text
    assert "Добавить ранг" in roles.text
    assert staff.status_code == 303
    assert staff.headers["location"].startswith("/community/members")
