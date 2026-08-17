from collections.abc import AsyncIterator

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from lab21_bot.models import Base
from lab21_bot.services.skill_catalog import clear_skills_cache
from lab21_bot.services.ranks_catalog import clear_ranks_cache


@pytest.fixture
async def session() -> AsyncIterator[AsyncSession]:
    clear_skills_cache()
    clear_ranks_cache()
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as db_session:
        yield db_session
    clear_skills_cache()
    clear_ranks_cache()
    await engine.dispose()
