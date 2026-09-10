from __future__ import annotations

from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Form, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from lab21_bot.admin.deps import (
    CurrentUser,
    DbSession,
    RequireManageSettings,
    SettingsDep,
)
from lab21_bot.admin.templating import render
from lab21_bot.llm.client import LLMClient, LLMError
from lab21_bot.services.admin_notify import (
    EVENT_LABELS,
    EVENT_TYPES,
    feed_latest_id,
    get_notification_prefs,
    list_notify_feed,
    prefs_from_form,
    save_notification_prefs,
)
from lab21_bot.services.llm_config import (
    LlmConfigError,
    LLM_COMMAND_LEGEND,
    get_llm_runtime,
    save_llm_settings,
)

router = APIRouter(tags=["settings"])


def _redirect(path: str, message: str | None = None, error: str | None = None) -> RedirectResponse:
    if error:
        return RedirectResponse(f"{path}?error={quote(error)}", status_code=303)
    return RedirectResponse(f"{path}?message={quote(message or 'Готово')}", status_code=303)


@router.get("/settings")
async def settings_root(_user: RequireManageSettings) -> RedirectResponse:
    return RedirectResponse("/settings/notifications", status_code=303)


@router.get("/settings/notifications", response_class=HTMLResponse)
async def notifications_page(
    request: Request,
    session: DbSession,
    user: RequireManageSettings,
) -> HTMLResponse:
    prefs = await get_notification_prefs(session)
    return await render(
        request,
        "settings_notifications.html",
        user=user,
        session=session,
        settings_section="notifications",
        prefs=prefs,
        event_types=EVENT_TYPES,
        event_labels=EVENT_LABELS,
    )


@router.post("/settings/notifications")
async def notifications_save(
    request: Request,
    session: DbSession,
    user: RequireManageSettings,
) -> RedirectResponse:
    form = dict(await request.form())
    prefs = prefs_from_form(form)
    await save_notification_prefs(session, user, prefs)
    return _redirect("/settings/notifications", "Настройки уведомлений сохранены")


@router.get("/settings/notifications/feed")
async def notifications_feed(
    session: DbSession,
    _user: CurrentUser,
    since_id: Annotated[int, Query()] = 0,
) -> JSONResponse:
    latest = await feed_latest_id(session)
    if since_id <= 0:
        # First poll: seed cursor without replaying history
        return JSONResponse({"events": [], "last_id": latest})
    events = await list_notify_feed(session, since_id=since_id)
    last_id = events[-1].id if events else since_id
    payload = [
        {
            "id": row.id,
            "event_type": row.event_type,
            "title": row.title,
            "body": row.body,
            "link": row.link,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }
        for row in events
    ]
    return JSONResponse({"events": payload, "last_id": last_id})


@router.get("/settings/llm", response_class=HTMLResponse)
async def llm_settings_page(
    request: Request,
    session: DbSession,
    settings: SettingsDep,
    user: RequireManageSettings,
) -> HTMLResponse:
    runtime = await get_llm_runtime(session, settings)
    client = LLMClient(settings)
    models: list[str] = []
    llm_ok = False
    try:
        llm_ok = await client.ping()
        if llm_ok:
            models = await client.list_models()
    except LLMError:
        llm_ok = False
    finally:
        await client.close()
    return await render(
        request,
        "settings_llm.html",
        user=user,
        session=session,
        settings_section="llm",
        runtime=runtime,
        models=models,
        llm_ok=llm_ok,
        llm_provider=settings.llm_provider,
        llm_device=settings.llm_device,
        llm_base_url=settings.llm_base_url,
        command_legend=LLM_COMMAND_LEGEND,
    )


@router.post("/settings/llm")
async def llm_settings_save(
    session: DbSession,
    settings: SettingsDep,
    user: RequireManageSettings,
    model: str = Form(...),
    temperature: float = Form(...),
    timeout_seconds: float = Form(...),
    command_suffix: str = Form(""),
) -> RedirectResponse:
    try:
        await save_llm_settings(
            session,
            user,
            settings,
            model=model,
            temperature=temperature,
            timeout_seconds=timeout_seconds,
            command_suffix=command_suffix,
        )
    except LlmConfigError as error:
        return _redirect("/settings/llm", error=str(error))
    return _redirect("/settings/llm", "Настройки LLM сохранены")
