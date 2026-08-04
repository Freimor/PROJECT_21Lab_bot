import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from lab21_bot.models import StaffRole, User
from lab21_bot.services.access import AccessDenied
from lab21_bot.services.settings import (
    SettingError,
    get_int_setting,
    set_int_setting,
)


async def test_magister_manages_runtime_settings(session: AsyncSession) -> None:
    magister = User(telegram_id=1, full_name="Магистр", staff_role=StaffRole.MAGISTER)
    watcher = User(telegram_id=2, full_name="Смотрящий", staff_role=StaffRole.WATCHER)
    session.add_all([magister, watcher])
    await session.flush()

    assert await get_int_setting(session, "transfer_daily_limit", 100) == 100
    await set_int_setting(session, magister, "transfer_daily_limit", 250)
    assert await get_int_setting(session, "transfer_daily_limit", 100) == 250

    with pytest.raises(AccessDenied):
        await set_int_setting(session, watcher, "transfer_daily_limit", 10)
    with pytest.raises(SettingError):
        await set_int_setting(session, magister, "unknown", 10)
