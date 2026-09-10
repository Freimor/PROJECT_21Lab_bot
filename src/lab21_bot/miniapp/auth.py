from __future__ import annotations

import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from urllib.parse import parse_qsl, unquote


class InitDataError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class TelegramWebAppUser:
    id: int
    first_name: str
    last_name: str | None = None
    username: str | None = None
    language_code: str | None = None
    is_premium: bool | None = None
    photo_url: str | None = None


def _data_check_string(parsed: dict[str, str]) -> str:
    pairs = sorted((key, value) for key, value in parsed.items() if key != "hash")
    return "\n".join(f"{key}={value}" for key, value in pairs)


def validate_init_data(
    init_data: str,
    bot_token: str,
    *,
    max_age_seconds: int = 86_400,
) -> dict[str, str]:
    if not init_data.strip():
        raise InitDataError("initData пуст")
    parsed = dict(parse_qsl(init_data, keep_blank_values=True))
    received_hash = parsed.pop("hash", None)
    if not received_hash:
        raise InitDataError("initData без hash")
    secret_key = hmac.new(
        b"WebAppData",
        bot_token.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    computed = hmac.new(
        secret_key,
        _data_check_string(parsed).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(computed, received_hash):
        raise InitDataError("Неверная подпись initData")
    auth_date_raw = parsed.get("auth_date")
    if auth_date_raw is None:
        raise InitDataError("initData без auth_date")
    try:
        auth_date = int(auth_date_raw)
    except ValueError as exc:
        raise InitDataError("Некорректный auth_date") from exc
    if max_age_seconds > 0 and int(time.time()) - auth_date > max_age_seconds:
        raise InitDataError("initData устарел")
    return parsed


def parse_webapp_user(parsed: dict[str, str]) -> TelegramWebAppUser:
    raw = parsed.get("user")
    if not raw:
        raise InitDataError("initData без user")
    try:
        payload = json.loads(unquote(raw))
    except json.JSONDecodeError as exc:
        raise InitDataError("Некорректный user в initData") from exc
    try:
        user_id = int(payload["id"])
        first_name = str(payload.get("first_name") or "").strip()
    except (KeyError, TypeError, ValueError) as exc:
        raise InitDataError("Некорректный user в initData") from exc
    if not first_name:
        raise InitDataError("Пустое имя пользователя")
    return TelegramWebAppUser(
        id=user_id,
        first_name=first_name,
        last_name=payload.get("last_name"),
        username=payload.get("username"),
        language_code=payload.get("language_code"),
        is_premium=payload.get("is_premium"),
        photo_url=payload.get("photo_url"),
    )


def webapp_user_full_name(user: TelegramWebAppUser) -> str:
    parts = [user.first_name]
    if user.last_name:
        parts.append(user.last_name)
    return " ".join(parts).strip()
