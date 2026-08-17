from __future__ import annotations

from pathlib import Path

from fastapi import Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession

from lab21_bot.data import (
    contrast_ink,
    rank_colors,
    rank_labels,
    rank_legend,
    removal_reason_labels,
    role_colors,
    role_labels,
    role_legend,
    skill_titles,
    skill_validation_descriptions,
    temper_color,
)
from lab21_bot.models import User
from lab21_bot.services.access import Permission, has_permission
from lab21_bot.services.faq_catalog import list_faq_pages
from lab21_bot.services.stats import NavAttention, nav_attention
from lab21_bot.services.feedback import count_pending_feedback

from lab21_bot.services.llm_config import LLM_PROMPT_PLACEHOLDERS
from lab21_bot.services.ranks_catalog import catalog_key
from lab21_bot.services.seasons import SEASON_ANNOUNCE_PLACEHOLDERS
from lab21_bot.services.templates import TEASER_PLACEHOLDERS

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
templates.env.globals["temper_color"] = temper_color
templates.env.globals["contrast_ink"] = contrast_ink
templates.env.globals["catalog_key"] = catalog_key
templates.env.globals["season_announce_placeholders"] = SEASON_ANNOUNCE_PLACEHOLDERS
templates.env.globals["teaser_placeholders"] = TEASER_PLACEHOLDERS
templates.env.globals["llm_prompt_placeholders"] = LLM_PROMPT_PLACEHOLDERS
templates.env.filters["catalog_key"] = catalog_key

REMOVAL_REASON_LABELS = removal_reason_labels()
FAQ_PAGES = list_faq_pages()


def nav_flags(user: User) -> dict[str, bool]:
    can_store = has_permission(user, Permission.MANAGE_STORE)
    can_orders = has_permission(user, Permission.MODERATE_ORDERS)
    is_staff = user.staff_role is not None
    return {
        "can_people": has_permission(user, Permission.MANAGE_STAFF)
        or has_permission(user, Permission.MANAGE_ECONOMY),
        "can_shop": can_store or can_orders,
        "can_store": can_store,
        "can_orders": can_orders,
        "can_publications": has_permission(user, Permission.MODERATE_CONTENT)
        or has_permission(user, Permission.MANAGE_SETTINGS),
        "can_economy": has_permission(user, Permission.MANAGE_ECONOMY),
        # Any staff can open the section; create/complete still check permissions.
        "can_gamification": is_staff,
        "can_settings": has_permission(user, Permission.MANAGE_SETTINGS),
        "can_feedback": is_staff,
    }


async def render(
    request: Request,
    name: str,
    *,
    user: User | None = None,
    session: AsyncSession | None = None,
    status_code: int = 200,
    **context: object,
) -> HTMLResponse:
    attention = NavAttention()
    pending_bugs = 0
    pending_upgrades = 0
    if user is not None and session is not None:
        attention = await nav_attention(session)
        pending_bugs, pending_upgrades = await count_pending_feedback(session)
    # Plain dict so Jinja always resolves attributes (and templates stay simple).
    badges = {
        "join_staff": attention.join_staff,
        "join_community": attention.join_community,
        "publications": attention.publications,
        "memes": attention.memes,
        "publications_total": attention.publications_total,
        "jobs": attention.jobs,
        "orders": attention.orders,
        "has_joins": attention.has_joins,
        "has_shop": attention.has_shop,
        "feedback_bugs": pending_bugs,
        "feedback_upgrades": pending_upgrades,
        "feedback_total": pending_bugs + pending_upgrades,
        "total": (
            attention.join_staff
            + attention.join_community
            + attention.publications_total
            + attention.jobs
            + attention.orders
            + pending_bugs
            + pending_upgrades
        ),
    }
    payload = {
        "request": request,
        "user": user,
        "nav": nav_flags(user) if user is not None else {},
        "badges": badges,
        "role_labels": role_labels(),
        "rank_labels": rank_labels(),
        "role_colors": role_colors(),
        "rank_colors": rank_colors(),
        "role_legend": role_legend(),
        "rank_legend": rank_legend(),
        "removal_reason_labels": REMOVAL_REASON_LABELS,
        "skill_titles": skill_titles(),
        "skill_validation_descriptions": skill_validation_descriptions(),
        "faq_pages": FAQ_PAGES,
        **context,
    }
    return templates.TemplateResponse(request, name, payload, status_code=status_code)
