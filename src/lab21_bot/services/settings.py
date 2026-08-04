from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from lab21_bot.models import AdminAction, BotSetting, User
from lab21_bot.services.access import Permission, require_permission

INTEGER_SETTINGS: dict[str, tuple[int, int]] = {
    "content_silence_days": (1, 90),
    "reminder_hour": (0, 23),
    "transfer_daily_limit": (0, 1_000_000),
}


class SettingError(RuntimeError):
    pass


async def get_int_setting(
    session: AsyncSession,
    key: str,
    default: int,
) -> int:
    setting = await session.get(BotSetting, key)
    if setting is None:
        return default
    value = setting.value.get("value")
    return int(value) if isinstance(value, int) else default


async def set_int_setting(
    session: AsyncSession,
    actor: User,
    key: str,
    value: int,
) -> BotSetting:
    require_permission(actor, Permission.MANAGE_SETTINGS)
    if key not in INTEGER_SETTINGS:
        raise SettingError("Эта настройка недоступна")
    minimum, maximum = INTEGER_SETTINGS[key]
    if not minimum <= value <= maximum:
        raise SettingError(f"Допустимый диапазон: {minimum}–{maximum}")
    setting = await session.get(BotSetting, key)
    if setting is None:
        setting = BotSetting(key=key, value={"value": value}, updated_by=actor.telegram_id)
        session.add(setting)
    else:
        setting.value = {"value": value}
        setting.updated_by = actor.telegram_id
    session.add(
        AdminAction(
            actor_id=actor.telegram_id,
            action="set_setting",
            details={"key": key, "value": value},
        )
    )
    await session.flush()
    return setting
