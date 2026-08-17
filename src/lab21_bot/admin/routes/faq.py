from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from lab21_bot.admin.deps import CurrentUser, DbSession
from lab21_bot.admin.templating import render
from lab21_bot.services.faq_catalog import faq_page_by_slug, list_faq_pages
from lab21_bot.services.markdown_lite import render_markdown

router = APIRouter(tags=["faq"])


@router.get("/faq", response_class=HTMLResponse, response_model=None)
async def faq_index(user: CurrentUser) -> RedirectResponse:
    pages = list_faq_pages()
    if not pages:
        return RedirectResponse("/", status_code=303)
    return RedirectResponse(f"/faq/{pages[0]['slug']}", status_code=303)


@router.get("/faq/{slug}", response_class=HTMLResponse, response_model=None)
async def faq_page(
    request: Request,
    session: DbSession,
    user: CurrentUser,
    slug: str,
) -> HTMLResponse | RedirectResponse:
    page = faq_page_by_slug(slug)
    if page is None:
        return RedirectResponse("/faq", status_code=303)
    source = Path(page["path"]).read_text(encoding="utf-8")
    return await render(
        request,
        "faq.html",
        user=user,
        session=session,
        active_slug=page["slug"],
        title=page["title"],
        body_html=render_markdown(source),
    )
