from __future__ import annotations

import json

import httpx
import pytest

from lab21_bot.services import notify as notify_mod
from lab21_bot.services.notify import TelegramSendError, send_telegram_message


@pytest.mark.asyncio
async def test_send_telegram_message_album_uses_media_group(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, object]] = []

    async def fake_request(method: str, url: str, **kwargs: object) -> httpx.Response:
        calls.append({"method": method, "url": url, **kwargs})
        assert "sendMediaGroup" in url
        data = kwargs.get("data")
        assert isinstance(data, dict)
        media = json.loads(str(data["media"]))
        assert len(media) == 2
        assert media[0]["type"] == "photo"
        assert media[0]["caption"] == "альбом"
        assert media[0]["media"] == "photo-1"
        assert media[1]["type"] == "document"  # animation → document in albums
        assert media[1]["media"] == "gif-1"
        return httpx.Response(
            200,
            json={
                "ok": True,
                "result": [
                    {"message_id": 101},
                    {"message_id": 102},
                ],
            },
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(notify_mod, "telegram_request", fake_request)
    message_id = await send_telegram_message(
        "1:test",
        -1001,
        "альбом",
        media=[
            {"type": "photo", "file_id": "photo-1"},
            {"type": "animation", "file_id": "gif-1"},
        ],
        parse_mode="HTML",
    )
    assert message_id == 101
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_send_telegram_message_album_long_text_followup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    long_text = "x" * 1025

    async def fake_request(method: str, url: str, **kwargs: object) -> httpx.Response:
        calls.append(url)
        if "sendMediaGroup" in url:
            return httpx.Response(
                200,
                json={"ok": True, "result": [{"message_id": 10}, {"message_id": 11}]},
                request=httpx.Request("POST", url),
            )
        assert "sendMessage" in url
        payload = kwargs.get("json")
        assert isinstance(payload, dict)
        assert payload["text"] == long_text
        return httpx.Response(
            200,
            json={"ok": True, "result": {"message_id": 12}},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(notify_mod, "telegram_request", fake_request)
    message_id = await send_telegram_message(
        "1:test",
        -1001,
        long_text,
        media=[
            {"type": "photo", "file_id": "a"},
            {"type": "photo", "file_id": "b"},
        ],
    )
    assert message_id == 12
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_send_telegram_message_album_error(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_request(method: str, url: str, **kwargs: object) -> httpx.Response:
        return httpx.Response(
            200,
            json={"ok": False, "description": "bad album"},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(notify_mod, "telegram_request", fake_request)
    with pytest.raises(TelegramSendError, match="bad album"):
        await send_telegram_message(
            "1:test",
            -1001,
            "hi",
            media=[
                {"type": "photo", "file_id": "a"},
                {"type": "photo", "file_id": "b"},
            ],
        )


@pytest.mark.asyncio
async def test_notify_telegram_user_returns_bool(monkeypatch: pytest.MonkeyPatch) -> None:
    async def ok_request(method: str, url: str, **kwargs: object) -> httpx.Response:
        return httpx.Response(
            200,
            json={"ok": True, "result": {"message_id": 1}},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(notify_mod, "telegram_request", ok_request)
    assert await notify_mod.notify_telegram_user("1:test", 42, "hi") is True

    async def fail_request(method: str, url: str, **kwargs: object) -> httpx.Response:
        raise httpx.ConnectError("down")

    monkeypatch.setattr(notify_mod, "telegram_request", fail_request)
    assert await notify_mod.notify_telegram_user("1:test", 42, "hi") is False
