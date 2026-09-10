from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter

from lab21_bot.miniapp.deps import MiniAppUser
from lab21_bot.services.faq_catalog import faq_page_by_slug, list_faq_pages
from lab21_bot.services.markdown_lite import render_markdown

router = APIRouter(tags=["miniapp-faq"])


@router.get("/faq")
async def faq_index(_user: MiniAppUser) -> dict:
    return {
        "pages": [
            {"slug": page["slug"], "title": page["title"]}
            for page in list_faq_pages()
        ]
    }


@router.get("/faq/{slug}")
async def faq_page(slug: str, _user: MiniAppUser) -> dict:
    page = faq_page_by_slug(slug)
    if page is None:
        return {"error": "not_found"}
    source = Path(page["path"]).read_text(encoding="utf-8")
    return {
        "slug": page["slug"],
        "title": page["title"],
        "html": render_markdown(source),
    }
