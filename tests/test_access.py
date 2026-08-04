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
    magister = User(telegram_id=1, full_name="Магистр", staff_role=StaffRole.MAGISTER)
    priest = User(telegram_id=2, full_name="Техножрец", staff_role=StaffRole.TECH_PRIEST)
    watcher = User(telegram_id=3, full_name="Смотрящий", staff_role=StaffRole.WATCHER)

    assert has_permission(magister, Permission.MANAGE_STAFF)
    assert has_permission(priest, Permission.MANAGE_ECONOMY)
    assert not has_permission(priest, Permission.MODERATE_CONTENT)
    assert has_permission(watcher, Permission.MODERATE_CONTENT)
    assert not has_permission(watcher, Permission.MANAGE_STAFF)


async def test_only_magister_changes_staff_and_cannot_demote_self(
    session: AsyncSession,
) -> None:
    magister = User(telegram_id=1, full_name="Магистр", staff_role=StaffRole.MAGISTER)
    target = User(telegram_id=2, full_name="Участник")
    watcher = User(telegram_id=3, full_name="Смотрящий", staff_role=StaffRole.WATCHER)
    session.add_all([magister, target, watcher])
    await session.flush()

    await set_staff_role(session, magister, target, StaffRole.TECH_PRIEST)
    assert target.staff_role is StaffRole.TECH_PRIEST

    with pytest.raises(AccessDenied):
        await set_staff_role(session, watcher, target, None)
    with pytest.raises(AccessDenied):
        await set_staff_role(session, magister, magister, None)
