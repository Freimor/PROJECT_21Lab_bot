from __future__ import annotations

from enum import StrEnum

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from lab21_bot.models import AdminAction, StaffRole, User


class Permission(StrEnum):
    MANAGE_STAFF = "manage_staff"
    MANAGE_SETTINGS = "manage_settings"
    MANAGE_STORE = "manage_store"
    MANAGE_ECONOMY = "manage_economy"
    MODERATE_CONTENT = "moderate_content"
    MODERATE_ORDERS = "moderate_orders"
    CREATE_STAFF_CONTENT = "create_staff_content"


ROLE_PERMISSIONS: dict[StaffRole, frozenset[Permission]] = {
    StaffRole.MAGISTER: frozenset(Permission),
    StaffRole.TECH_PRIEST: frozenset(
        {
            Permission.MANAGE_ECONOMY,
            Permission.CREATE_STAFF_CONTENT,
        }
    ),
    StaffRole.WATCHER: frozenset(
        {
            Permission.MODERATE_CONTENT,
            Permission.MODERATE_ORDERS,
            Permission.CREATE_STAFF_CONTENT,
        }
    ),
}


class AccessDenied(RuntimeError):
    pass


async def register_user(
    session: AsyncSession,
    telegram_id: int,
    full_name: str,
    username: str | None,
) -> User:
    user = await session.get(User, telegram_id)
    if user is None:
        user = User(telegram_id=telegram_id, full_name=full_name, username=username)
        session.add(user)
        await session.flush()
    else:
        user.full_name = full_name
        user.username = username
        user.is_active = True
    return user


def has_permission(user: User, permission: Permission) -> bool:
    return user.staff_role is not None and permission in ROLE_PERMISSIONS[user.staff_role]


def require_permission(user: User, permission: Permission) -> None:
    if not has_permission(user, permission):
        raise AccessDenied(f"Требуется право: {permission.value}")


async def set_staff_role(
    session: AsyncSession,
    actor: User,
    target: User,
    role: StaffRole | None,
) -> None:
    require_permission(actor, Permission.MANAGE_STAFF)
    if target.telegram_id == actor.telegram_id and role is not StaffRole.MAGISTER:
        raise AccessDenied("Магистр не может снять собственные полномочия")
    previous = target.staff_role
    target.staff_role = role
    session.add(
        AdminAction(
            actor_id=actor.telegram_id,
            action="set_staff_role",
            target_id=target.telegram_id,
            details={
                "from": previous.value if previous else None,
                "to": role.value if role else None,
            },
        )
    )


async def list_staff(session: AsyncSession) -> list[User]:
    result = await session.scalars(
        select(User).where(User.staff_role.is_not(None)).order_by(User.full_name)
    )
    return list(result)
