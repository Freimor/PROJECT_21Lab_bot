from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from lab21_bot.config import Settings
from lab21_bot.models import Base, StaffRole, User


def create_engine(settings: Settings) -> AsyncEngine:
    return create_async_engine(settings.database_url, pool_pre_ping=True)


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


async def session_scope(
    factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    async with factory() as session:
        async with session.begin():
            yield session


async def bootstrap_database(
    engine: AsyncEngine,
    factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    *,
    create_schema: bool = False,
) -> None:
    if create_schema:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    async with factory.begin() as session:
        user = await session.get(User, settings.bootstrap_magister_id)
        if user is None:
            session.add(
                User(
                    telegram_id=settings.bootstrap_magister_id,
                    full_name="Магистр",
                    staff_role=StaffRole.MAGISTER,
                )
            )
        elif user.staff_role is not StaffRole.MAGISTER:
            user.staff_role = StaffRole.MAGISTER
