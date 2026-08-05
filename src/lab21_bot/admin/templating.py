from __future__ import annotations

from pathlib import Path

from fastapi import Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from lab21_bot.models import User
from lab21_bot.services.access import Permission, has_permission

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

ROLE_LABELS = {
    "lord": "Лорд",
    "magister": "Магистр",
    "tech_priest": "Техножрец",
    "watcher": "Смотрящий",
}

RANK_LABELS = {
    "novice": "Послушник",
    "adept": "Адепт",
}

ROLE_LEGEND = [
    {
        "key": "lord",
        "label": "Лорд",
        "badge": "админ",
        "desc": "Полный доступ, включая обновление и перезагрузку системы.",
    },
    {
        "key": "magister",
        "label": "Магистр",
        "badge": "админ",
        "desc": "Все функции Лорда, кроме обновления и перезагрузки системы.",
    },
    {
        "key": "tech_priest",
        "label": "Техножрец",
        "badge": "сотрудник",
        "desc": "Экономика благодати/респекта и создание служебных постов.",
    },
    {
        "key": "watcher",
        "label": "Смотрящий",
        "badge": "сотрудник",
        "desc": "Модерация контента и выдача заказов.",
    },
]

RANK_LEGEND = [
    {"label": "Послушник", "level": "0"},
    {"label": "Адепт", "level": "1"},
]

REMOVAL_REASON_LABELS = {
    "none": "без причины",
    "rules": "Нарушение правил",
}


def nav_flags(user: User) -> dict[str, bool]:
    can_store = has_permission(user, Permission.MANAGE_STORE)
    can_orders = has_permission(user, Permission.MODERATE_ORDERS)
    return {
        "can_people": has_permission(user, Permission.MANAGE_STAFF)
        or has_permission(user, Permission.MANAGE_ECONOMY),
        "can_shop": can_store or can_orders,
        "can_store": can_store,
        "can_orders": can_orders,
        "can_moderation": has_permission(user, Permission.MODERATE_CONTENT),
        "can_economy": has_permission(user, Permission.MANAGE_ECONOMY),
    }


def render(
    request: Request,
    name: str,
    *,
    user: User | None = None,
    status_code: int = 200,
    **context: object,
) -> HTMLResponse:
    payload = {
        "request": request,
        "user": user,
        "nav": nav_flags(user) if user is not None else {},
        "role_labels": ROLE_LABELS,
        "rank_labels": RANK_LABELS,
        "role_legend": ROLE_LEGEND,
        "rank_legend": RANK_LEGEND,
        "removal_reason_labels": REMOVAL_REASON_LABELS,
        **context,
    }
    return templates.TemplateResponse(request, name, payload, status_code=status_code)
