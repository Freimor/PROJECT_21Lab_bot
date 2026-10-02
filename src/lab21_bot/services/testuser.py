"""Switch the miniapp identity to a fixture participant."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from lab21_bot.models import CommunityRank, User
from lab21_bot.services.access import AccessDenied, Permission, require_permission

# Synthetic telegram id. The row exists only in the database.
TEST_USER_ID = 7_700_000_000_001
TEST_USER_NAME = "Тестовый участник"
TEST_BALANCE = 300


class TestUserError(RuntimeError):
    __test__ = False


def is_test_user(user: User) -> bool:
    return user.telegram_id == TEST_USER_ID


async def ensure_test_user(session: AsyncSession) -> User:
    user = await session.get(User, TEST_USER_ID)
    if user is None:
        user = User(
            telegram_id=TEST_USER_ID,
            full_name=TEST_USER_NAME,
            rank=CommunityRank.ADEPT,
            balance=TEST_BALANCE,
            is_approved=True,
            is_active=True,
            sales_mode=True,
            market_intro_seen=True,
            staff_role=None,
        )
        session.add(user)
        await session.flush()
        return user
    user.full_name = TEST_USER_NAME
    user.staff_role = None
    user.is_approved = True
    user.is_active = True
    user.sales_mode = True
    user.market_intro_seen = True
    if user.rank is None:
        user.rank = CommunityRank.ADEPT
    await session.flush()
    return user


async def set_testuser_allowed(
    session: AsyncSession,
    actor: User,
    target: User,
    *,
    allowed: bool,
) -> None:
    require_permission(actor, Permission.MANAGE_STAFF)
    if target.staff_role is None or target.telegram_id == TEST_USER_ID:
        raise AccessDenied("Тестовый вход включают только сотруднику")
    target.can_use_testuser = allowed
    if not allowed:
        target.testuser_active = False
    await session.flush()


async def toggle_testuser(session: AsyncSession, actor: User) -> bool:
    if actor.staff_role is None or not actor.can_use_testuser:
        raise TestUserError(
            "Тестовый вход для тебя не включён. "
            "Его включают в админке, в карточке сотрудника."
        )
    actor.testuser_active = not bool(actor.testuser_active)
    if actor.testuser_active:
        await ensure_test_user(session)
    await session.flush()
    return bool(actor.testuser_active)


async def resolve_miniapp_user(session: AsyncSession, real: User) -> User:
    if real.staff_role is None or not real.can_use_testuser or not real.testuser_active:
        return real
    return await ensure_test_user(session)
