from __future__ import annotations

import hashlib
import hmac
import time
from typing import Any

from lab21_bot.config import Settings
from lab21_bot.models import User

SESSION_USER_KEY = "admin_user_id"
AUTH_MAX_AGE_SECONDS = 86400


class AuthError(RuntimeError):
    pass


def verify_telegram_login(
    payload: dict[str, Any],
    bot_token: str,
    *,
    now: int | None = None,
    max_age_seconds: int = AUTH_MAX_AGE_SECONDS,
) -> dict[str, Any]:
    """Validate Telegram Login Widget data per official algorithm."""
    received_hash = payload.get("hash")
    if not received_hash or not isinstance(received_hash, str):
        raise AuthError("Отсутствует подпись Telegram Login")

    check_pairs = []
    for key, value in payload.items():
        if key == "hash" or value is None or value == "":
            continue
        check_pairs.append(f"{key}={value}")
    check_pairs.sort()
    data_check_string = "\n".join(check_pairs)

    secret_key = hashlib.sha256(bot_token.encode()).digest()
    expected = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, received_hash):
        raise AuthError("Неверная подпись Telegram Login")

    auth_date_raw = payload.get("auth_date")
    if auth_date_raw is None:
        raise AuthError("Некорректный auth_date")
    try:
        auth_date = int(auth_date_raw)
    except (TypeError, ValueError) as exc:
        raise AuthError("Некорректный auth_date") from exc

    current = now if now is not None else int(time.time())
    if current - auth_date > max_age_seconds:
        raise AuthError("Сессия Telegram Login устарела")

    return payload


def require_staff_user(user: User | None) -> User:
    if user is None or user.staff_role is None or user.is_active is False:
        raise AuthError("Доступ только для сотрудников со staff_role")
    return user


def password_login_allowed(settings: Settings) -> bool:
    return settings.admin_password is not None and bool(settings.admin_password.get_secret_value())


def verify_admin_password(settings: Settings, password: str) -> None:
    if not password_login_allowed(settings):
        raise AuthError("Аварийный вход по паролю отключён")
    expected = settings.admin_password.get_secret_value() if settings.admin_password else ""
    password_digest = hashlib.sha256(password.encode()).digest()
    expected_digest = hashlib.sha256(expected.encode()).digest()
    if not hmac.compare_digest(password_digest, expected_digest):
        raise AuthError("Неверный пароль")
