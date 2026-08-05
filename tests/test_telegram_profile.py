from __future__ import annotations

from lab21_bot.services.telegram_profile import _compose_full_name


def test_compose_full_name() -> None:
    assert _compose_full_name({"first_name": "Иван", "last_name": "Петров"}) == "Иван Петров"
    assert _compose_full_name({"first_name": "Иван", "username": "ivan"}) == "Иван"
    assert _compose_full_name({"username": "ivan"}) == "ivan"
    assert _compose_full_name({}) == "Участник"
