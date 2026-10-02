from __future__ import annotations

import time
from typing import Annotated, Any

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from lab21_bot.admin.auth import (
    OTP_IDENTITY_KEY,
    OTP_SESSION_KEY,
    SESSION_USER_KEY,
    AuthError,
    check_login_code,
    mark_otp_sent,
    new_login_code,
    otp_challenge,
    otp_cooldown_active,
    password_login_allowed,
    require_staff_user,
    telegram_bot_id,
    verify_admin_password,
    verify_telegram_login,
)
from lab21_bot.admin.deps import DbSession, SettingsDep, get_current_user
from lab21_bot.admin.templating import render
from lab21_bot.config import Settings
from lab21_bot.models import User
from lab21_bot.services.access import find_user
from lab21_bot.services.notify import TelegramSendError, send_telegram_message
from lab21_bot.services.telegram_profile import sync_user_profile

router = APIRouter(tags=["auth"])

_LOGIN_ERRORS = {
    "telegram": "Не удалось подтвердить вход через Telegram.",
    "staff": "Этот аккаунт Telegram не числится сотрудником.",
    "delivery": "Бот не смог написать в личку. Откройте бота, нажмите Start и запросите код снова.",
    "code": "Код неверный или устарел. Запросите новый.",
}
_CODE_SENT_NOTICE = (
    "Если это сотрудник и бот может написать в личку, код уже в Telegram. Он действует 5 минут."
)


def _telegram_login_available(settings: Settings) -> bool:
    bot_username = (settings.telegram_bot_username or "").lstrip("@")
    host = (settings.admin_base_url or "").lower()
    return bool(bot_username) and "localhost" not in host and "127.0.0.1" not in host


def _code_pending(request: Request) -> bool:
    challenge = request.session.get(OTP_SESSION_KEY)
    return isinstance(challenge, dict) and "code_hash" in challenge


async def _render_login(
    request: Request,
    settings: Settings,
    *,
    error: str | None = None,
    notice: str | None = None,
    status_code: int = 200,
) -> HTMLResponse:
    identity = request.session.get(OTP_IDENTITY_KEY)
    return await render(
        request,
        "login.html",
        error=error,
        notice=notice,
        bot_username=(settings.telegram_bot_username or "").lstrip("@"),
        telegram_bot_id=telegram_bot_id(settings.telegram_bot_token.get_secret_value()),
        telegram_login_available=_telegram_login_available(settings),
        password_enabled=password_login_allowed(settings),
        bootstrap_magister_id=settings.bootstrap_magister_id,
        admin_base_url=settings.admin_base_url,
        code_pending=_code_pending(request),
        identity=identity if isinstance(identity, str) else "",
        status_code=status_code,
    )


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
    error = _LOGIN_ERRORS.get(error_code or "")
    notice = _CODE_SENT_NOTICE if request.query_params.get("sent") == "1" else None
    return await _render_login(request, settings, error=error, notice=notice)


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
    except (AuthError, KeyError, TypeError, ValueError):
        return RedirectResponse("/login?error=telegram", status_code=303)
    user = await session.get(User, telegram_id)
    try:
        require_staff_user(user)
    except AuthError:
        return RedirectResponse("/login?error=staff", status_code=303)
    request.session[SESSION_USER_KEY] = telegram_id
    return RedirectResponse("/", status_code=303)


@router.post("/auth/code/request", response_model=None)
async def request_login_code(
    request: Request,
    session: DbSession,
    settings: SettingsDep,
    identity: Annotated[str, Form()],
) -> RedirectResponse:
    typed = identity.strip()
    request.session[OTP_IDENTITY_KEY] = typed
    user = await find_user(session, typed)
    try:
        staff = require_staff_user(user)
    except AuthError:
        staff = None

    now = time.time()
    if staff is None:
        # Same page shape as a real send, so the form does not reveal who is staff.
        request.session[OTP_SESSION_KEY] = otp_challenge(
            0,
            new_login_code(),
            settings.session_secret,
            now=int(now),
        )
        return RedirectResponse("/login?sent=1", status_code=303)
    if otp_cooldown_active(staff.telegram_id, now):
        return RedirectResponse("/login?sent=1", status_code=303)

    code = new_login_code()
    request.session[OTP_SESSION_KEY] = otp_challenge(
        staff.telegram_id,
        code,
        settings.session_secret,
        now=int(now),
    )
    text = (
        f"Код входа в админку Lab21: {code}\n"
        f"Адрес: {settings.admin_base_url}\n"
        "Действует 5 минут. Если вы не запрашивали вход — проигнорируйте это сообщение."
    )
    try:
        await send_telegram_message(
            settings.telegram_bot_token.get_secret_value(),
            staff.telegram_id,
            text,
        )
    except TelegramSendError:
        request.session.pop(OTP_SESSION_KEY, None)
        return RedirectResponse("/login?error=delivery", status_code=303)
    mark_otp_sent(staff.telegram_id, now)
    return RedirectResponse("/login?sent=1", status_code=303)


@router.post("/auth/code", response_model=None)
async def submit_login_code(
    request: Request,
    session: DbSession,
    settings: SettingsDep,
    code: Annotated[str, Form()],
) -> RedirectResponse:
    challenge = request.session.get(OTP_SESSION_KEY)
    status, updated = check_login_code(
        challenge if isinstance(challenge, dict) else None,
        code,
        settings.session_secret,
        now=int(time.time()),
    )
    if updated is None:
        request.session.pop(OTP_SESSION_KEY, None)
    else:
        request.session[OTP_SESSION_KEY] = updated
    if status != "ok":
        return RedirectResponse("/login?error=code", status_code=303)

    raw_user_id: Any = challenge.get("user_id") if isinstance(challenge, dict) else None
    try:
        telegram_id = int(raw_user_id)
    except (TypeError, ValueError):
        return RedirectResponse("/login?error=code", status_code=303)
    user = await session.get(User, telegram_id)
    try:
        require_staff_user(user)
    except AuthError:
        return RedirectResponse("/login?error=code", status_code=303)
    request.session.pop(OTP_IDENTITY_KEY, None)
    request.session[SESSION_USER_KEY] = telegram_id
    return RedirectResponse("/", status_code=303)


@router.post("/auth/password", response_model=None)
async def password_login(
    request: Request,
    session: DbSession,
    settings: SettingsDep,
    telegram_id: Annotated[int, Form()],
    password: Annotated[str, Form()],
) -> RedirectResponse | HTMLResponse:
    try:
        verify_admin_password(settings, password)
        user = await session.get(User, telegram_id)
        require_staff_user(user)
        assert user is not None
        request.session.pop(OTP_SESSION_KEY, None)
        request.session.pop(OTP_IDENTITY_KEY, None)
        request.session[SESSION_USER_KEY] = user.telegram_id
        await sync_user_profile(
            session,
            user,
            settings.telegram_bot_token.get_secret_value(),
        )
    except AuthError as exc:
        return await _render_login(request, settings, error=str(exc), status_code=400)
    return RedirectResponse("/", status_code=303)


@router.post("/logout")
async def logout(request: Request) -> RedirectResponse:
    request.session.clear()
    return RedirectResponse("/login", status_code=303)
