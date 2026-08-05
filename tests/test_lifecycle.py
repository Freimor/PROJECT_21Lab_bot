import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from lab21_bot.config import Settings
from lab21_bot.models import StaffRole, User
from lab21_bot.services.access import AccessDenied
from lab21_bot.services.lifecycle import (
    LifecycleError,
    UpdateStatus,
    check_github_updates,
    consume_restart_result,
    request_restart,
)


def settings(tmp_path: Path, sha: str = "abc123") -> Settings:
    return Settings(
        telegram_bot_token="token",
        bootstrap_magister_id=1,
        main_channel_id=-1001,
        staff_chat_id=-1002,
        control_dir=str(tmp_path),
        app_git_sha=sha,
        github_repo="Freimor/PROJECT_21Lab_bot",
        github_branch="main",
    )


async def test_check_github_updates_detects_new_commit(tmp_path: Path) -> None:
    response = AsyncMock()
    response.raise_for_status = lambda: None
    response.json = lambda: {"sha": "ffffffffffffffffffffffffffffffffffffffff"}
    client = AsyncMock()
    client.get = AsyncMock(return_value=response)
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)

    with patch("lab21_bot.services.lifecycle.httpx.AsyncClient", return_value=client):
        status = await check_github_updates(settings(tmp_path, sha="abc123"))

    assert status.update_available is True
    assert status.remote_sha is not None
    assert "Доступно обновление" in status.message


async def test_request_restart_writes_signal(session: AsyncSession, tmp_path: Path) -> None:
    lord = User(telegram_id=1, full_name="Лорд", staff_role=StaffRole.LORD)
    magister = User(telegram_id=3, full_name="Магистр", staff_role=StaffRole.MAGISTER)
    watcher = User(telegram_id=2, full_name="Смотрящий", staff_role=StaffRole.WATCHER)
    session.add_all([lord, magister, watcher])
    await session.flush()
    cfg = settings(tmp_path)
    status = UpdateStatus(
        current_sha="abc123",
        remote_sha="def456",
        branch="main",
        update_available=True,
        message="Доступно обновление",
    )

    with pytest.raises(AccessDenied):
        await request_restart(session, watcher, cfg, reason="nope", update_status=status)
    with pytest.raises(AccessDenied):
        await request_restart(session, magister, cfg, reason="nope", update_status=status)

    request = await request_restart(
        session,
        lord,
        cfg,
        reason="manual",
        update_status=status,
    )
    signal = tmp_path / "restart.requested"
    assert signal.exists()
    payload = json.loads(signal.read_text(encoding="utf-8"))
    assert payload["requested_by"] == 1
    assert request.apply_updates is True

    with pytest.raises(LifecycleError):
        await request_restart(
            session,
            lord,
            cfg,
            reason="duplicate",
            update_status=status,
        )


async def test_consume_restart_result(session: AsyncSession, tmp_path: Path) -> None:
    cfg = settings(tmp_path)
    result = tmp_path / "restart.result"
    result.write_text(
        json.dumps(
            {
                "requested_by": 1,
                "status": "ok",
                "applied_sha": "deadbeef",
                "updated": True,
                "detail": "done",
            }
        ),
        encoding="utf-8",
    )
    payload = await consume_restart_result(session, cfg)
    assert payload is not None
    assert payload["status"] == "ok"
    assert not result.exists()
