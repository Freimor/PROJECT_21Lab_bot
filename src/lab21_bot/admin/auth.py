from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from typing import Any

from lab21_bot.config import Settings
from lab21_bot.models import User

SESSION_USER_KEY = "admin_user_id"
OTP_SESSION_KEY = "admin_otp"
OTP_IDENTITY_KEY = "admin_otp_identity"
AUTH_MAX_AGE_SECONDS = 86400
OTP_TTL_SECONDS = 300
OTP_MAX_ATTEMPTS = 5
OTP_COOLDOWN_SECONDS = 60

_otp_sent_at: dict[int, float] = {}


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


def telegram_bot_id(bot_token: str) -> int | None:
    bot_id = bot_token.split(":", 1)[0]
    if not bot_id.isdigit():
        return None
    return int(bot_id)


def new_login_code() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def login_code_digest(code: str, telegram_id: int, secret: str) -> str:
    message = f"{telegram_id}:{code.strip()}".encode()
    return hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()


def otp_challenge(telegram_id: int, code: str, secret: str, *, now: int) -> dict[str, int | str]:
    return {
        "user_id": telegram_id,
        "code_hash": login_code_digest(code, telegram_id, secret),
        "expires": now + OTP_TTL_SECONDS,
        "attempts": 0,
    }


def otp_cooldown_active(
    telegram_id: int,
    now: float,
    *,
    cooldown: float = OTP_COOLDOWN_SECONDS,
) -> bool:
    last = _otp_sent_at.get(telegram_id)
    return last is not None and now - last < cooldown


def mark_otp_sent(telegram_id: int, now: float) -> None:
    _otp_sent_at[telegram_id] = now


def reset_otp_cooldowns() -> None:
    _otp_sent_at.clear()


def check_login_code(
    challenge: dict[str, Any] | None,
    code: str,
    secret: str,
    *,
    now: int,
) -> tuple[str, dict[str, Any] | None]:
    """Return (status, challenge). A None challenge means the caller should drop it."""
    if not challenge or "user_id" not in challenge or "code_hash" not in challenge:
        return "missing", None
    try:
        expires = int(challenge["expires"])
        attempts = int(challenge["attempts"])
        telegram_id = int(challenge["user_id"])
        stored_hash = str(challenge["code_hash"])
    except (TypeError, ValueError):
        return "missing", None
    if attempts >= OTP_MAX_ATTEMPTS:
        return "locked", None
    if now > expires:
        return "expired", None

    attempts += 1
    expected = login_code_digest(code, telegram_id, secret)
    if hmac.compare_digest(expected, stored_hash):
        return "ok", None
    if attempts >= OTP_MAX_ATTEMPTS:
        return "locked", None
    updated = dict(challenge)
    updated["attempts"] = attempts
    return "mismatch", updated


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
