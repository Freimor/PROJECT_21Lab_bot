from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from lab21_bot.admin.deps import (
    CurrentUser,
    DbSession,
    RequireManageSettings,
    SettingsDep,
)
from lab21_bot.admin.templating import render
from lab21_bot.models import ContentStatus
from lab21_bot.services.access import Permission, has_permission
from lab21_bot.services.content import KIND_LABELS, STATUS_LABELS, list_posts_journal
from lab21_bot.services.llm_config import (
    LlmConfigError,
    get_llm_runtime,
    save_llm_prompts,
)

router = APIRouter(tags=["publications-llm"])


def _redirect(path: str, message: str | None = None, error: str | None = None) -> RedirectResponse:
    if error:
        return RedirectResponse(f"{path}?error={quote(error)}", status_code=303)
    return RedirectResponse(f"{path}?message={quote(message or 'Готово')}", status_code=303)


def _pub_nav(user: CurrentUser) -> dict[str, bool]:
    return {
        "can_settings": has_permission(user, Permission.MANAGE_SETTINGS),
        "can_queue": has_permission(user, Permission.MODERATE_CONTENT),
    }


@router.get("/publications/llm")
async def llm_posts_root(user: CurrentUser) -> RedirectResponse:
    nav = _pub_nav(user)
    if not nav["can_settings"] and not nav["can_queue"]:
        return RedirectResponse("/", status_code=303)
    return RedirectResponse("/publications/llm/journal", status_code=303)


@router.get("/publications/llm/settings")
async def llm_settings_redirect() -> RedirectResponse:
    return RedirectResponse("/settings/llm", status_code=303)


@router.post("/publications/llm/settings")
async def llm_settings_post_redirect() -> RedirectResponse:
    return RedirectResponse("/settings/llm", status_code=303)


@router.get("/publications/llm/templates", response_class=HTMLResponse)
async def llm_templates_page(
    request: Request,
    session: DbSession,
    settings: SettingsDep,
    user: RequireManageSettings,
) -> HTMLResponse:
    runtime = await get_llm_runtime(session, settings)
    nav = _pub_nav(user)
    return await render(
        request,
        "publications_llm_templates.html",
        user=user,
        session=session,
        pub_section="llm_templates",
        prompts=runtime.prompts,
        **nav,
    )


@router.post("/publications/llm/templates")
async def llm_templates_save(
    session: DbSession,
    user: RequireManageSettings,
    system: str = Form(...),
    staff_post: str = Form(...),
    interview_post: str = Form(...),
    job_post: str = Form(...),
) -> RedirectResponse:
    try:
        await save_llm_prompts(
            session,
            user,
            {
                "system": system,
                "staff_post": staff_post,
                "interview_post": interview_post,
                "job_post": job_post,
            },
        )
    except LlmConfigError as error:
        return _redirect("/publications/llm/templates", error=str(error))
    return _redirect("/publications/llm/templates", "Шаблоны сохранены")


@router.get("/publications/llm/journal", response_class=HTMLResponse)
async def llm_journal_page(
    request: Request,
    session: DbSession,
    user: CurrentUser,
    status: str | None = None,
) -> HTMLResponse:
    nav = _pub_nav(user)
    if not nav["can_settings"] and not nav["can_queue"]:
        return RedirectResponse("/", status_code=303)
    status_filter: ContentStatus | None = None
    if status:
        try:
            status_filter = ContentStatus(status)
        except ValueError:
            status_filter = None
    items = await list_posts_journal(session, status=status_filter)
    return await render(
        request,
        "publications_llm_journal.html",
        user=user,
        session=session,
        pub_section="llm_journal",
        items=items,
        status_filter=status_filter.value if status_filter else "",
        status_labels={s.value: label for s, label in STATUS_LABELS.items()},
        kind_labels={k.value: v for k, v in KIND_LABELS.items()},
        **nav,
    )
