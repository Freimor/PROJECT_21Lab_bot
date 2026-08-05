from __future__ import annotations

from enum import StrEnum
from typing import cast

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from lab21_bot.models import AdminAction, StaffRole, User


class Permission(StrEnum):
    MANAGE_STAFF = "manage_staff"
    MANAGE_SETTINGS = "manage_settings"
    MANAGE_SYSTEM = "manage_system"
    MANAGE_STORE = "manage_store"
    MANAGE_ECONOMY = "manage_economy"
    MODERATE_CONTENT = "moderate_content"
    MODERATE_ORDERS = "moderate_orders"
    CREATE_STAFF_CONTENT = "create_staff_content"


_ALL_EXCEPT_SYSTEM = frozenset(p for p in Permission if p is not Permission.MANAGE_SYSTEM)

ROLE_PERMISSIONS: dict[StaffRole, frozenset[Permission]] = {
    StaffRole.LORD: frozenset(Permission),
    StaffRole.MAGISTER: _ALL_EXCEPT_SYSTEM,
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
        user = User(
            telegram_id=telegram_id,
            full_name=full_name,
            username=username,
            is_approved=False,
        )
        session.add(user)
        await session.flush()
    else:
        user.full_name = full_name
        user.username = username
        user.is_active = True
    return user


def require_approved(user: User) -> None:
    if not user.is_approved:
        raise AccessDenied("Заявка ещё не одобрена администратором")


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
    if (
        target.telegram_id == actor.telegram_id
        and actor.staff_role is StaffRole.LORD
        and role is not StaffRole.LORD
    ):
        raise AccessDenied("Лорд не может снять собственные полномочия")
    previous = target.staff_role
    target.staff_role = role
    if role is not None:
        target.balance = 0
        target.respect = 0
        target.is_approved = True
        target.is_active = True
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
        select(User)
        .where(User.staff_role.is_not(None), User.is_active.is_(True))
        .order_by(User.full_name)
    )
    return list(result)


async def find_user(session: AsyncSession, query: str) -> User | None:
    raw = query.strip()
    if not raw:
        return None
    if raw.isdigit() or (raw.startswith("-") and raw[1:].isdigit()):
        return await session.get(User, int(raw))
    username = raw.lstrip("@").lower()
    return cast(
        User | None,
        await session.scalar(select(User).where(func.lower(User.username) == username).limit(1)),
    )
