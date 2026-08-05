from __future__ import annotations

import asyncio
import json
import os
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from lab21_bot.config import Settings
from lab21_bot.models import AdminAction, BotSetting, User
from lab21_bot.services.access import Permission, require_permission

RESTART_SIGNAL = "restart.requested"
RESTART_RESULT = "restart.result"
LAST_RESTART_SETTING = "last_restart_result"


class LifecycleError(RuntimeError):
    pass


@dataclass(slots=True)
class UpdateStatus:
    current_sha: str
    remote_sha: str | None
    branch: str
    update_available: bool
    message: str
    compare_url: str | None = None


@dataclass(slots=True)
class RestartRequest:
    requested_by: int
    requested_at: str
    reason: str
    apply_updates: bool = True
    current_sha: str = "unknown"
    remote_sha: str | None = None


def control_file(settings: Settings, name: str) -> str:
    return os.path.join(settings.control_dir, name)


def _prepare_control_dir(control_dir: str) -> None:
    os.makedirs(control_dir, exist_ok=True)


def _write_json(path: str, payload: dict[str, Any]) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)


def _read_json(path: str) -> dict[str, Any]:
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError("restart payload must be an object")
    return data


def _unlink(path: str) -> None:
    try:
        os.remove(path)
    except FileNotFoundError:
        return


async def check_github_updates(settings: Settings) -> UpdateStatus:
    current = settings.app_git_sha or "unknown"
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "lab21-bot",
    }
    if settings.github_token:
        headers["Authorization"] = f"Bearer {settings.github_token.get_secret_value()}"

    url = f"https://api.github.com/repos/{settings.github_repo}/commits/{settings.github_branch}"
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.get(url, headers=headers)
            response.raise_for_status()
            payload = response.json()
            remote = str(payload.get("sha") or "")
    except httpx.HTTPError as error:
        return UpdateStatus(
            current_sha=current,
            remote_sha=None,
            branch=settings.github_branch,
            update_available=False,
            message=f"Не удалось проверить GitHub: {error}",
        )

    if not remote:
        return UpdateStatus(
            current_sha=current,
            remote_sha=None,
            branch=settings.github_branch,
            update_available=False,
            message="GitHub не вернул SHA коммита",
        )

    same = current != "unknown" and (remote.startswith(current) or current.startswith(remote))
    available = not same
    if current == "unknown":
        message = f"Текущая сборка без SHA. На GitHub ({settings.github_branch}): {remote[:12]}"
    elif available:
        message = f"Доступно обновление: {current[:12]} → {remote[:12]} ({settings.github_branch})"
    else:
        message = f"Уже актуальны: {current[:12]} ({settings.github_branch})"

    return UpdateStatus(
        current_sha=current,
        remote_sha=remote,
        branch=settings.github_branch,
        update_available=available,
        message=message,
        compare_url=(
            f"https://github.com/{settings.github_repo}/compare/{current}...{remote}"
            if current != "unknown"
            else None
        ),
    )


async def request_restart(
    session: AsyncSession,
    actor: User,
    settings: Settings,
    *,
    reason: str,
    update_status: UpdateStatus | None = None,
) -> RestartRequest:
    require_permission(actor, Permission.MANAGE_SYSTEM)
    try:
        await asyncio.to_thread(_prepare_control_dir, settings.control_dir)
    except OSError as error:
        raise LifecycleError(f"Каталог управления недоступен: {error}") from error

    signal = control_file(settings, RESTART_SIGNAL)
    if await asyncio.to_thread(os.path.exists, signal):
        raise LifecycleError("Перезагрузка уже запрошена и ожидает watchdog")

    status = update_status or await check_github_updates(settings)
    request = RestartRequest(
        requested_by=actor.telegram_id,
        requested_at=datetime.now(UTC).isoformat(),
        reason=reason.strip() or "manual reboot",
        apply_updates=True,
        current_sha=status.current_sha,
        remote_sha=status.remote_sha,
    )
    await asyncio.to_thread(_write_json, signal, asdict(request))
    session.add(
        AdminAction(
            actor_id=actor.telegram_id,
            action="request_restart",
            details=asdict(request),
        )
    )
    await session.flush()
    return request


async def consume_restart_result(
    session: AsyncSession,
    settings: Settings,
) -> dict[str, Any] | None:
    path = control_file(settings, RESTART_RESULT)
    if not await asyncio.to_thread(os.path.exists, path):
        setting = await session.get(BotSetting, LAST_RESTART_SETTING)
        return setting.value if setting else None

    try:
        payload = await asyncio.to_thread(_read_json, path)
    except (OSError, ValueError, json.JSONDecodeError):
        await asyncio.to_thread(_unlink, path)
        return None

    await asyncio.to_thread(_unlink, path)

    setting = await session.get(BotSetting, LAST_RESTART_SETTING)
    if setting is None:
        session.add(
            BotSetting(
                key=LAST_RESTART_SETTING,
                value=payload,
                updated_by=payload.get("requested_by"),
            )
        )
    else:
        setting.value = payload
        setting.updated_by = payload.get("requested_by")
    await session.flush()
    return payload
