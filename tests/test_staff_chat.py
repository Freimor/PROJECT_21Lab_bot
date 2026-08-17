import pytest

from lab21_bot.services.staff_chat import invite_to_staff_chat, kick_from_staff_chat


@pytest.fixture
def token() -> str:
    return "test-token"


async def test_invite_to_staff_chat_sends_one_time_link(
    token: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[str, dict[str, object]]] = []

    async def fake_post(_token: str, method: str, payload: dict[str, object]) -> dict[str, object]:
        calls.append((method, payload))
        if method == "createChatInviteLink":
            return {"ok": True, "result": {"invite_link": "https://t.me/+testInvite"}}
        return {"ok": True, "result": {"message_id": 1}}

    monkeypatch.setattr("lab21_bot.services.staff_chat._post", fake_post)
    link = await invite_to_staff_chat(token, -1001, 42)
    assert link == "https://t.me/+testInvite"
    assert calls[0][0] == "createChatInviteLink"
    assert calls[0][1]["member_limit"] == 1
    assert calls[1][0] == "sendMessage"
    assert "https://t.me/+testInvite" in str(calls[1][1]["text"])


async def test_kick_from_staff_chat_bans_then_unbans(
    token: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []

    async def fake_post(_token: str, method: str, payload: dict[str, object]) -> dict[str, object]:
        calls.append(method)
        return {"ok": True, "result": True}

    monkeypatch.setattr("lab21_bot.services.staff_chat._post", fake_post)
    assert await kick_from_staff_chat(token, -1001, 42) is True
    assert calls == ["banChatMember", "unbanChatMember"]
