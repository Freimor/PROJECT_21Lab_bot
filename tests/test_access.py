import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from lab21_bot.models import StaffRole, User
from lab21_bot.services.access import (
    AccessDenied,
    Permission,
    has_permission,
    register_user,
    set_staff_role,
)


async def test_registration_updates_profile_without_losing_role(session: AsyncSession) -> None:
    user = await register_user(session, 10, "Первое имя", "old")
    user.staff_role = StaffRole.WATCHER
    await session.flush()

    updated = await register_user(session, 10, "Новое имя", "new")

    assert updated is user
    assert updated.full_name == "Новое имя"
    assert updated.username == "new"
    assert updated.staff_role is StaffRole.WATCHER


def test_role_permission_matrix() -> None:
    lord = User(telegram_id=1, full_name="Лорд", staff_role=StaffRole.LORD)
    magister = User(telegram_id=4, full_name="Магистр", staff_role=StaffRole.MAGISTER)
    priest = User(telegram_id=2, full_name="Техножрец", staff_role=StaffRole.TECH_PRIEST)
    watcher = User(telegram_id=3, full_name="Смотрящий", staff_role=StaffRole.WATCHER)

    assert has_permission(lord, Permission.MANAGE_STAFF)
    assert has_permission(lord, Permission.MANAGE_SYSTEM)
    assert has_permission(magister, Permission.MANAGE_STAFF)
    assert has_permission(magister, Permission.MANAGE_SETTINGS)
    assert not has_permission(magister, Permission.MANAGE_SYSTEM)
    assert has_permission(priest, Permission.MANAGE_ECONOMY)
    assert not has_permission(priest, Permission.MODERATE_CONTENT)
    assert has_permission(watcher, Permission.MODERATE_CONTENT)
    assert not has_permission(watcher, Permission.MANAGE_STAFF)


async def test_only_staff_managers_change_roles_and_lord_cannot_demote_self(
    session: AsyncSession,
) -> None:
    lord = User(telegram_id=1, full_name="Лорд", staff_role=StaffRole.LORD)
    target = User(telegram_id=2, full_name="Участник")
    watcher = User(telegram_id=3, full_name="Смотрящий", staff_role=StaffRole.WATCHER)
    session.add_all([lord, target, watcher])
    await session.flush()

    await set_staff_role(session, lord, target, StaffRole.TECH_PRIEST)
    assert target.staff_role is StaffRole.TECH_PRIEST

    with pytest.raises(AccessDenied):
        await set_staff_role(session, watcher, target, None)
    with pytest.raises(AccessDenied):
        await set_staff_role(session, lord, lord, None)


async def test_only_one_lord_allowed(session: AsyncSession) -> None:
    lord = User(telegram_id=1, full_name="Лорд", staff_role=StaffRole.LORD)
    candidate = User(telegram_id=2, full_name="Кандидат", staff_role=StaffRole.MAGISTER)
    session.add_all([lord, candidate])
    await session.flush()

    with pytest.raises(AccessDenied, match="только один"):
        await set_staff_role(session, lord, candidate, StaffRole.LORD)
