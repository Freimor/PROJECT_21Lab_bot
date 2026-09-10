from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lab21_bot.config import Settings, get_settings
from lab21_bot.miniapp.auth import (
    InitDataError,
    TelegramWebAppUser,
    parse_webapp_user,
    validate_init_data,
    webapp_user_full_name,
)
from lab21_bot.models import User
from lab21_bot.services.access import AccessDenied, Permission, has_permission, register_user


async def get_db_session(request: Request) -> AsyncIterator[AsyncSession]:
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def get_settings_dep(request: Request) -> Settings:
    state_settings = getattr(request.app.state, "settings", None)
    if state_settings is not None:
        return state_settings
    return get_settings()


DbSession = Annotated[AsyncSession, Depends(get_db_session)]
SettingsDep = Annotated[Settings, Depends(get_settings_dep)]


def _extract_init_data(authorization: str | None) -> str:
    if not authorization:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Нет Authorization")
    scheme, _, value = authorization.partition(" ")
    if scheme.lower() != "tma" or not value.strip():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Ожидается Authorization: tma <initData>",
        )
    return value.strip()


async def get_telegram_user(
    settings: SettingsDep,
    authorization: Annotated[str | None, Header()] = None,
) -> TelegramWebAppUser:
    init_data = _extract_init_data(authorization)
    try:
        parsed = validate_init_data(
            init_data,
            settings.telegram_bot_token.get_secret_value(),
        )
        return parse_webapp_user(parsed)
    except InitDataError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc


async def get_current_user(
    session: DbSession,
    tg_user: Annotated[TelegramWebAppUser, Depends(get_telegram_user)],
) -> User:
    full_name = webapp_user_full_name(tg_user)
    user = await register_user(session, tg_user.id, full_name, tg_user.username)
    await session.flush()
    return user


async def require_approved_user(
    user: Annotated[User, Depends(get_current_user)],
) -> User:
    if not user.is_approved:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Заявка не одобрена")
    return user


TgUser = Annotated[TelegramWebAppUser, Depends(get_telegram_user)]
MiniAppUser = Annotated[User, Depends(get_current_user)]
ApprovedUser = Annotated[User, Depends(require_approved_user)]


def require_perm(permission: Permission):
    async def dependency(user: MiniAppUser) -> User:
        if not has_permission(user, permission):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Нет права: {permission.value}",
            )
        return user

    return dependency


def api_error(status_code: int, detail: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail=detail)


def map_service_error(exc: Exception, *, forbidden: bool = False) -> HTTPException:
    if isinstance(exc, AccessDenied):
        return api_error(status.HTTP_403_FORBIDDEN, str(exc))
    if forbidden:
        return api_error(status.HTTP_403_FORBIDDEN, str(exc))
    return api_error(status.HTTP_400_BAD_REQUEST, str(exc))
