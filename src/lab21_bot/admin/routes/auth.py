from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from lab21_bot.admin.auth import (
    SESSION_USER_KEY,
    AuthError,
    password_login_allowed,
    require_staff_user,
    verify_admin_password,
    verify_telegram_login,
)
from lab21_bot.admin.deps import DbSession, SettingsDep, get_current_user
from lab21_bot.admin.templating import render
from lab21_bot.models import User
from lab21_bot.services.telegram_profile import sync_user_profile

router = APIRouter(tags=["auth"])


@router.get("/login", response_class=HTMLResponse, response_model=None)
async def login_page(
    request: Request,
    session: DbSession,
    settings: SettingsDep,
) -> HTMLResponse | RedirectResponse:
    current = await get_current_user(request, session)
    if current is not None and current.staff_role is not None:
        return RedirectResponse("/", status_code=303)
    error_code = request.query_params.get("error")
    error = "Не удалось войти через Telegram" if error_code == "telegram" else None
    bot_username = (settings.telegram_bot_username or "").lstrip("@")
    host = (settings.admin_base_url or "").lower()
    telegram_login_available = (
        bool(bot_username) and "localhost" not in host and "127.0.0.1" not in host
    )
    return render(
        request,
        "login.html",
        error=error,
        bot_username=bot_username,
        telegram_login_available=telegram_login_available,
        password_enabled=password_login_allowed(settings),
        bootstrap_magister_id=settings.bootstrap_magister_id,
        admin_base_url=settings.admin_base_url,
    )


@router.get("/auth/telegram")
async def telegram_login(
    request: Request,
    session: DbSession,
    settings: SettingsDep,
) -> RedirectResponse:
    try:
        payload = dict(request.query_params)
        verified = verify_telegram_login(
            payload,
            settings.telegram_bot_token.get_secret_value(),
        )
        telegram_id = int(verified["id"])
        user = await session.get(User, telegram_id)
        require_staff_user(user)
        request.session[SESSION_USER_KEY] = telegram_id
    except (AuthError, KeyError, TypeError, ValueError):
        return RedirectResponse("/login?error=telegram", status_code=303)
    return RedirectResponse("/", status_code=303)


@router.post("/auth/password", response_model=None)
async def password_login(
    request: Request,
    session: DbSession,
    settings: SettingsDep,
    telegram_id: Annotated[int, Form()],
    password: Annotated[str, Form()],
) -> RedirectResponse | HTMLResponse:
    bot_username = (settings.telegram_bot_username or "").lstrip("@")
    host = (settings.admin_base_url or "").lower()
    telegram_login_available = (
        bool(bot_username) and "localhost" not in host and "127.0.0.1" not in host
    )
    try:
        verify_admin_password(settings, password)
        user = await session.get(User, telegram_id)
        require_staff_user(user)
        assert user is not None
        request.session[SESSION_USER_KEY] = user.telegram_id
        await sync_user_profile(
            session,
            user,
            settings.telegram_bot_token.get_secret_value(),
        )
    except AuthError as exc:
        return render(
            request,
            "login.html",
            error=str(exc),
            bot_username=bot_username,
            telegram_login_available=telegram_login_available,
            password_enabled=password_login_allowed(settings),
            bootstrap_magister_id=settings.bootstrap_magister_id,
            admin_base_url=settings.admin_base_url,
            status_code=400,
        )
    return RedirectResponse("/", status_code=303)


@router.post("/logout")
async def logout(request: Request) -> RedirectResponse:
    request.session.clear()
    return RedirectResponse("/login", status_code=303)
