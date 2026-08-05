from __future__ import annotations

import hashlib
import hmac
import time

import pytest
from pydantic import SecretStr

from lab21_bot.admin.auth import (
    AuthError,
    password_login_allowed,
    require_staff_user,
    verify_admin_password,
    verify_telegram_login,
)
from lab21_bot.config import Settings
from lab21_bot.models import StaffRole, User
from lab21_bot.services.access import Permission, has_permission


def _settings(**overrides: object) -> Settings:
    payload = {
        "telegram_bot_token": SecretStr("123456:TESTTOKEN"),
        "bootstrap_magister_id": 1,
        "main_channel_id": -1001,
        "staff_chat_id": -1002,
        "database_url": "sqlite+aiosqlite:///:memory:",
        **overrides,
    }
    return Settings(**payload)  # type: ignore[arg-type]


def _signed_telegram_payload(bot_token: str, **fields: object) -> dict[str, object]:
    payload = {key: str(value) for key, value in fields.items()}
    pairs = [f"{key}={value}" for key, value in sorted(payload.items())]
    secret_key = hashlib.sha256(bot_token.encode()).digest()
    payload["hash"] = hmac.new(secret_key, "\n".join(pairs).encode(), hashlib.sha256).hexdigest()
    return payload


def test_verify_telegram_login_ok() -> None:
    token = "123456:TESTTOKEN"
    now = int(time.time())
    payload = _signed_telegram_payload(
        token,
        id=42,
        first_name="Magister",
        username="lab21",
        auth_date=now,
    )
    verified = verify_telegram_login(payload, token, now=now)
    assert verified["id"] == "42"


def test_verify_telegram_login_bad_hash() -> None:
    token = "123456:TESTTOKEN"
    now = int(time.time())
    payload = _signed_telegram_payload(
        token,
        id=42,
        first_name="Magister",
        auth_date=now,
    )
    payload["hash"] = "0" * 64
    with pytest.raises(AuthError, match="подпись"):
        verify_telegram_login(payload, token, now=now)


def test_verify_telegram_login_expired() -> None:
    token = "123456:TESTTOKEN"
    now = int(time.time())
    payload = _signed_telegram_payload(
        token,
        id=42,
        first_name="Magister",
        auth_date=now - 100_000,
    )
    with pytest.raises(AuthError, match="устарела"):
        verify_telegram_login(payload, token, now=now)


def test_password_login_gate() -> None:
    settings = _settings(admin_password=SecretStr("secret-pass"))
    assert password_login_allowed(settings)
    verify_admin_password(settings, "secret-pass")
    with pytest.raises(AuthError, match="пароль"):
        verify_admin_password(settings, "wrong")


def test_password_login_disabled() -> None:
    settings = _settings(admin_password=None)
    assert not password_login_allowed(settings)
    with pytest.raises(AuthError, match="отключён"):
        verify_admin_password(settings, "anything")


def test_require_staff_user() -> None:
    staff = User(
        telegram_id=1,
        full_name="Lord",
        staff_role=StaffRole.LORD,
    )
    assert require_staff_user(staff) is staff

    civilian = User(telegram_id=2, full_name="Novice", staff_role=None)
    with pytest.raises(AuthError):
        require_staff_user(civilian)


def test_permission_matrix_for_admin_sections() -> None:
    lord = User(telegram_id=1, full_name="L", staff_role=StaffRole.LORD)
    magister = User(telegram_id=4, full_name="M", staff_role=StaffRole.MAGISTER)
    priest = User(telegram_id=2, full_name="P", staff_role=StaffRole.TECH_PRIEST)
    watcher = User(telegram_id=3, full_name="W", staff_role=StaffRole.WATCHER)

    assert has_permission(lord, Permission.MANAGE_STAFF)
    assert has_permission(lord, Permission.MANAGE_SYSTEM)
    assert has_permission(magister, Permission.MANAGE_STORE)
    assert not has_permission(magister, Permission.MANAGE_SYSTEM)
    assert has_permission(priest, Permission.MANAGE_ECONOMY)
    assert not has_permission(priest, Permission.MANAGE_STORE)
    assert has_permission(watcher, Permission.MODERATE_ORDERS)
    assert has_permission(watcher, Permission.MODERATE_CONTENT)
    assert not has_permission(watcher, Permission.MANAGE_ECONOMY)
