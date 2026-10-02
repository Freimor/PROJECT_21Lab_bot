from __future__ import annotations

from typing import Annotated
from urllib.parse import urlencode

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from lab21_bot.admin.deps import CurrentUser, DbSession, RequireModerateContent, SettingsDep
from lab21_bot.admin.templating import render
from lab21_bot.models import FeedbackKind, FeedbackStatus
from lab21_bot.services.feedback import (
    KIND_LABELS,
    STATUS_LABELS,
    FeedbackError,
    REACTION_ACCEPTED,
    REACTION_DONE,
    REACTION_REJECTED,
    complete_feedback,
    count_pending_feedback,
    decide_feedback,
    list_feedback,
)
from lab21_bot.services.telegram_profile import TelegramProfileError, download_telegram_file

router = APIRouter(tags=["feedback"])


def _redirect(
    path: str = "/feedback/bugs",
    message: str | None = None,
    error: str | None = None,
    status: str | None = None,
) -> RedirectResponse:
    params: dict[str, str] = {}
    if status:
        params["status"] = status
    if error:
        params["error"] = error
    elif message:
        params["message"] = message or "Готово"
    query = f"?{urlencode(params)}" if params else ""
    return RedirectResponse(f"{path}{query}", status_code=303)


def _status_filter(status: str | None) -> FeedbackStatus | None:
    if status == "all":
        return None
    if status == "accepted":
        return FeedbackStatus.ACCEPTED
    if status == "rejected":
        return FeedbackStatus.REJECTED
    if status == "done":
        return FeedbackStatus.DONE
    return FeedbackStatus.PENDING


@router.get("/feedback")
async def feedback_root(_user: CurrentUser) -> RedirectResponse:
    return RedirectResponse("/feedback/bugs", status_code=303)


@router.get("/feedback/bugs", response_class=HTMLResponse)
async def feedback_bugs_page(
    request: Request,
    session: DbSession,
    user: CurrentUser,
    status: str | None = None,
) -> HTMLResponse:
    status_filter = _status_filter(status)
    items = await list_feedback(
        session, kind=FeedbackKind.BUG, status=status_filter
    )
    bugs, upgrades = await count_pending_feedback(session)
    return await render(
        request,
        "feedback.html",
        user=user,
        session=session,
        feedback_section="bugs",
        items=items,
        status_filter=status or "pending",
        kind_labels={k.value: v for k, v in KIND_LABELS.items()},
        status_labels={k.value: v for k, v in STATUS_LABELS.items()},
        pending_bugs=bugs,
        pending_upgrades=upgrades,
    )


@router.get("/feedback/upgrades", response_class=HTMLResponse)
async def feedback_upgrades_page(
    request: Request,
    session: DbSession,
    user: CurrentUser,
    status: str | None = None,
) -> HTMLResponse:
    status_filter = _status_filter(status)
    items = await list_feedback(
        session, kind=FeedbackKind.UPGRADE, status=status_filter
    )
    bugs, upgrades = await count_pending_feedback(session)
    return await render(
        request,
        "feedback.html",
        user=user,
        session=session,
        feedback_section="upgrades",
        items=items,
        status_filter=status or "pending",
        kind_labels={k.value: v for k, v in KIND_LABELS.items()},
        status_labels={k.value: v for k, v in STATUS_LABELS.items()},
        pending_bugs=bugs,
        pending_upgrades=upgrades,
    )


@router.get("/feedback/{item_id}/media/{index}")
async def feedback_media(
    item_id: int,
    index: int,
    session: DbSession,
    settings: SettingsDep,
    _user: CurrentUser,
) -> Response:
    from lab21_bot.models import FeedbackReport

    item = await session.get(FeedbackReport, item_id)
    if item is None or index < 0 or index >= len(item.media or []):
        return Response(status_code=404)
    entry = item.media[index]
    file_id = entry.get("file_id")
    if not file_id:
        return Response(status_code=404)
    try:
        data, content_type = await download_telegram_file(
            settings.telegram_bot_token.get_secret_value(),
            str(file_id),
        )
    except TelegramProfileError:
        return Response(status_code=404)
    return Response(content=data, media_type=content_type or "application/octet-stream")


async def _set_reaction(settings, chat_id: int, message_id: int, emoji: str) -> None:
    from lab21_bot.telegram_client import telegram_api_post

    token = settings.telegram_bot_token.get_secret_value()
    try:
        await telegram_api_post(
            token,
            "setMessageReaction",
            {
                "chat_id": chat_id,
                "message_id": message_id,
                "reaction": [{"type": "emoji", "emoji": emoji}],
            },
            request_timeout=20.0,
        )
    except Exception:
        pass


@router.post("/feedback/{item_id}/accept")
async def feedback_accept(
    item_id: int,
    session: DbSession,
    settings: SettingsDep,
    actor: RequireModerateContent,
    note: Annotated[str, Form()] = "",
) -> RedirectResponse:
    try:
        row = await decide_feedback(session, actor, item_id, accept=True, note=note)
        await _set_reaction(settings, row.chat_id, row.message_id, REACTION_ACCEPTED)
        path = (
            "/feedback/bugs"
            if row.kind is FeedbackKind.BUG
            else "/feedback/upgrades"
        )
        return _redirect(path, f"Принято #{item_id}")
    except FeedbackError as exc:
        return _redirect(error=str(exc))


@router.post("/feedback/{item_id}/reject")
async def feedback_reject(
    item_id: int,
    session: DbSession,
    settings: SettingsDep,
    actor: RequireModerateContent,
    note: Annotated[str, Form()] = "",
) -> RedirectResponse:
    try:
        row = await decide_feedback(session, actor, item_id, accept=False, note=note)
        await _set_reaction(settings, row.chat_id, row.message_id, REACTION_REJECTED)
        path = (
            "/feedback/bugs"
            if row.kind is FeedbackKind.BUG
            else "/feedback/upgrades"
        )
        return _redirect(path, f"Отклонено #{item_id}")
    except FeedbackError as exc:
        return _redirect(error=str(exc))


@router.post("/feedback/{item_id}/done")
async def feedback_done(
    item_id: int,
    session: DbSession,
    settings: SettingsDep,
    actor: RequireModerateContent,
) -> RedirectResponse:
    try:
        row = await complete_feedback(session, actor, item_id)
        await _set_reaction(settings, row.chat_id, row.message_id, REACTION_DONE)
        path = (
            "/feedback/bugs"
            if row.kind is FeedbackKind.BUG
            else "/feedback/upgrades"
        )
        return _redirect(path, f"Done #{item_id}", status="accepted")
    except FeedbackError as exc:
        return _redirect(error=str(exc))
