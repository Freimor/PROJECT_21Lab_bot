from __future__ import annotations

from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from lab21_bot.admin.deps import DbSession, RequireModerateContent
from lab21_bot.admin.templating import render
from lab21_bot.models import ContentStatus
from lab21_bot.services.content import ContentError, list_moderation_queue, moderate_content

router = APIRouter(prefix="/moderation", tags=["moderation"])


@router.get("", response_class=HTMLResponse)
async def moderation_page(
    request: Request,
    session: DbSession,
    user: RequireModerateContent,
) -> HTMLResponse:
    items = await list_moderation_queue(session)
    return render(
        request,
        "moderation.html",
        user=user,
        items=items,
        message=request.query_params.get("message"),
        error=request.query_params.get("error"),
    )


@router.post("/{item_id}/decide")
async def moderation_decide(
    item_id: int,
    session: DbSession,
    reviewer: RequireModerateContent,
    decision: Annotated[str, Form()],
    note: Annotated[str, Form()] = "",
    edited_text: Annotated[str, Form()] = "",
) -> RedirectResponse:
    mapping = {
        "approve": ContentStatus.APPROVED,
        "reject": ContentStatus.REJECTED,
        "needs_info": ContentStatus.NEEDS_INFO,
    }
    try:
        status = mapping[decision]
        await moderate_content(
            session,
            reviewer,
            item_id,
            status,
            edited_text=edited_text.strip() or None,
            note=note.strip() or None,
        )
        return RedirectResponse(
            "/moderation?message=" + quote("Решение сохранено"),
            status_code=303,
        )
    except (ContentError, KeyError) as exc:
        return RedirectResponse(f"/moderation?error={quote(str(exc))}", status_code=303)
