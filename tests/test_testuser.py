import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from lab21_bot.models import CommunityRank, StaffRole, User
from lab21_bot.services.access import AccessDenied, set_staff_role
from lab21_bot.services.commands import commands_for_user
from lab21_bot.services.testuser import (
    TEST_BALANCE,
    TEST_USER_ID,
    TEST_USER_NAME,
    TestUserError,
    resolve_miniapp_user,
    set_testuser_allowed,
    toggle_testuser,
)


def _staff(telegram_id: int, role: StaffRole = StaffRole.WATCHER) -> User:
    return User(telegram_id=telegram_id, full_name=f"Сотрудник {telegram_id}", staff_role=role)


async def test_toggle_requires_admin_allowance(session: AsyncSession) -> None:
    actor = _staff(10)
    session.add(actor)
    await session.flush()

    with pytest.raises(TestUserError):
        await toggle_testuser(session, actor)

    assert await resolve_miniapp_user(session, actor) is actor


async def test_toggle_swaps_miniapp_identity(session: AsyncSession) -> None:
    lord = _staff(1, StaffRole.LORD)
    actor = _staff(10)
    session.add_all([lord, actor])
    await session.flush()
    await set_testuser_allowed(session, lord, actor, allowed=True)

    assert [item.command for item in commands_for_user(actor)] == ["bow", "testuser"]
    assert await toggle_testuser(session, actor) is True

    viewed = await resolve_miniapp_user(session, actor)
    assert viewed.telegram_id == TEST_USER_ID
    assert viewed.full_name == TEST_USER_NAME
    assert viewed.is_approved is True
    assert viewed.sales_mode is True
    assert viewed.staff_role is None
    assert viewed.balance == TEST_BALANCE
    assert viewed.rank is CommunityRank.ADEPT

    assert await toggle_testuser(session, actor) is False
    assert await resolve_miniapp_user(session, actor) is actor


async def test_revoke_and_role_clear_stop_impersonation(session: AsyncSession) -> None:
    lord = _staff(1, StaffRole.LORD)
    actor = _staff(10)
    outsider = User(telegram_id=20, full_name="Участник")
    session.add_all([lord, actor, outsider])
    await session.flush()
    await set_testuser_allowed(session, lord, actor, allowed=True)
    await toggle_testuser(session, actor)

    await set_testuser_allowed(session, lord, actor, allowed=False)
    assert actor.can_use_testuser is False
    assert actor.testuser_active is False
    assert await resolve_miniapp_user(session, actor) is actor

    await set_testuser_allowed(session, lord, actor, allowed=True)
    await toggle_testuser(session, actor)
    await set_staff_role(session, lord, actor, None)
    assert actor.can_use_testuser is False
    assert actor.testuser_active is False
    assert await resolve_miniapp_user(session, actor) is actor

    with pytest.raises(AccessDenied):
        await set_testuser_allowed(session, lord, outsider, allowed=True)
