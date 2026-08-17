from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lab21_bot.admin.auth import SESSION_USER_KEY
from lab21_bot.config import Settings, get_settings
from lab21_bot.models import User
from lab21_bot.services.access import Permission, has_permission


async def get_db_session(request: Request) -> AsyncIterator[AsyncSession]:
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


DbSession = Annotated[AsyncSession, Depends(get_db_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


async def get_current_user(request: Request, session: DbSession) -> User | None:
    user_id = request.session.get(SESSION_USER_KEY)
    if user_id is None:
        return None
    try:
        telegram_id = int(user_id)
    except (TypeError, ValueError):
        return None
    return await session.get(User, telegram_id)


async def require_user(request: Request, session: DbSession) -> User:
    user = await get_current_user(request, session)
    if user is None or user.staff_role is None or user.is_active is False:
        raise HTTPException(
            status_code=status.HTTP_303_SEE_OTHER,
            headers={"Location": "/login"},
        )
    return user


CurrentUser = Annotated[User, Depends(require_user)]


def require_perm(permission: Permission) -> Callable[..., Awaitable[User]]:
    async def dependency(user: CurrentUser) -> User:
        if not has_permission(user, permission):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Нет права: {permission.value}",
            )
        return user

    dependency.__name__ = f"require_{permission.value}"
    return dependency


RequireManageStaff = Annotated[User, Depends(require_perm(Permission.MANAGE_STAFF))]
RequireManageStore = Annotated[User, Depends(require_perm(Permission.MANAGE_STORE))]
RequireModerateOrders = Annotated[User, Depends(require_perm(Permission.MODERATE_ORDERS))]
RequireModerateContent = Annotated[User, Depends(require_perm(Permission.MODERATE_CONTENT))]
RequireManageEconomy = Annotated[User, Depends(require_perm(Permission.MANAGE_ECONOMY))]
RequireManageSettings = Annotated[User, Depends(require_perm(Permission.MANAGE_SETTINGS))]
RequireCreateStaffContent = Annotated[
    User, Depends(require_perm(Permission.CREATE_STAFF_CONTENT))
]
