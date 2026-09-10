from __future__ import annotations

import hashlib
import hmac
import time
from urllib.parse import urlencode

import pytest

from lab21_bot.miniapp.auth import (
    InitDataError,
    parse_webapp_user,
    validate_init_data,
    webapp_user_full_name,
)


def _sign_init_data(parsed: dict[str, str], bot_token: str) -> str:
    data_check = "\n".join(f"{k}={v}" for k, v in sorted(parsed.items()))
    secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    return hmac.new(secret, data_check.encode(), hashlib.sha256).hexdigest()


def _make_init_data(bot_token: str, **extra: str) -> str:
    payload = {
        "auth_date": str(int(time.time())),
        "user": (
            '{"id":12345,"first_name":"Test","last_name":"User","username":"tester"}'
        ),
        **extra,
    }
    payload["hash"] = _sign_init_data(payload, bot_token)
    return urlencode(payload)


def test_validate_init_data_ok() -> None:
    token = "123456:ABC-DEF"
    init_data = _make_init_data(token)
    parsed = validate_init_data(init_data, token)
    assert "auth_date" in parsed


def test_validate_init_data_bad_hash() -> None:
    token = "123456:ABC-DEF"
    init_data = _make_init_data(token)
    broken = init_data.replace("hash=", "hash=x")
    with pytest.raises(InitDataError):
        validate_init_data(broken, token)


def test_validate_init_data_expired() -> None:
    token = "123456:ABC-DEF"
    payload = {
        "auth_date": "1",
        "user": '{"id":1,"first_name":"A"}',
    }
    payload["hash"] = _sign_init_data(payload, token)
    init_data = urlencode(payload)
    with pytest.raises(InitDataError):
        validate_init_data(init_data, token, max_age_seconds=60)


def test_parse_webapp_user() -> None:
    token = "123456:ABC-DEF"
    init_data = _make_init_data(token)
    parsed = validate_init_data(init_data, token)
    user = parse_webapp_user(parsed)
    assert user.id == 12345
    assert webapp_user_full_name(user) == "Test User"
