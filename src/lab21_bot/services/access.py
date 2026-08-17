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

# Fallback when the DB catalog is not loaded yet (tests / early boot).
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


async def require_approved_user(session: AsyncSession, user: User) -> User:
    """Like ``require_approved``, but distinguishes «нет заявки» vs «ждёт решения»."""
    if user.is_approved:
        return user
    from lab21_bot.data import phrase
    from lab21_bot.services.applications import get_pending_application

    pending = await get_pending_application(session, user.telegram_id)
    if pending is not None:
        raise AccessDenied(phrase("onboarding", "pending_wait"))
    raise AccessDenied(phrase("onboarding", "need_apply"))


def has_permission(user: User, permission: Permission) -> bool:
    if user.staff_role is None:
        return False
    from lab21_bot.services.ranks_catalog import get_roles_snapshot, permissions_for_role

    if get_roles_snapshot():
        return permission in permissions_for_role(str(user.staff_role))
    if isinstance(user.staff_role, StaffRole):
        return permission in ROLE_PERMISSIONS.get(user.staff_role, frozenset())
    return False


def require_permission(user: User, permission: Permission) -> None:
    if not has_permission(user, permission):
        raise AccessDenied("У тебя нет прав на это действие")


def _role_is_unique(role: StaffRole | str | None) -> bool:
    if role is None:
        return False
    from lab21_bot.services.ranks_catalog import role_by_id

    item = role_by_id(str(role))
    if item is not None:
        return bool(item.get("is_unique"))
    return role == StaffRole.LORD or str(role) == StaffRole.LORD.value


async def set_staff_role(
    session: AsyncSession,
    actor: User,
    target: User,
    role: StaffRole | str | None,
) -> None:
    require_permission(actor, Permission.MANAGE_STAFF)
    actor_unique = _role_is_unique(actor.staff_role)
    if (
        target.telegram_id == actor.telegram_id
        and actor_unique
        and not _role_is_unique(role)
    ):
        raise AccessDenied("Лорд не может снять собственные полномочия")
    if _role_is_unique(role):
        existing = await session.scalar(
            select(User).where(
                User.staff_role == str(role),
                User.telegram_id != target.telegram_id,
            )
        )
        if existing is not None:
            if str(role) == StaffRole.LORD.value:
                raise AccessDenied("Тёмный лорд в системе может быть только один")
            raise AccessDenied("Уникальная роль уже назначена другому пользователю")
    if role is not None:
        from lab21_bot.services.ranks_catalog import role_by_id

        if role_by_id(str(role)) is None and not isinstance(role, StaffRole):
            raise AccessDenied(f"Неизвестная роль: {role}")
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
                "from": str(previous) if previous else None,
                "to": str(role) if role else None,
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
