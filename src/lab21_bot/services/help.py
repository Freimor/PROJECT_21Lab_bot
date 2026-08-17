from __future__ import annotations

from lab21_bot.data import phrase, role_label
from lab21_bot.models import StaffRole, User
from lab21_bot.services.access import Permission, has_permission


def _can_propose_important(user: User) -> bool:
    return user.staff_role in {StaffRole.LORD, StaffRole.MAGISTER}


def build_help_text(user: User) -> str:
    lines: list[str] = [phrase("help", "title"), ""]

    if user.staff_role is None:
        lines.append(phrase("help", "intro_member"))
        lines.append(phrase("help", "status"))
        lines.append(phrase("help", "skills"))
        lines.append(phrase("help", "ritual"))
        lines.append(phrase("help", "card"))
        lines.append(phrase("help", "shop"))
        lines.append(phrase("help", "order_service"))
        lines.append(phrase("help", "job_notify"))
        lines.append(phrase("help", "submit"))
        lines.append(phrase("help", "submit_post"))
        lines.append(phrase("help", "submit_meme"))
    else:
        lines.append(
            phrase("help", "intro_staff", role=role_label(str(user.staff_role)))
        )
        lines.append(phrase("help", "card"))
        if has_permission(user, Permission.MANAGE_ECONOMY):
            lines.append(phrase("help", "staff_bless"))
        lines.append(phrase("help", "submit"))
        lines.append(phrase("help", "submit_post"))
        if _can_propose_important(user):
            lines.append(phrase("help", "submit_important"))
        lines.append(phrase("help", "submit_meme"))
        lines.append(phrase("help", "staff_menu"))
        if has_permission(user, Permission.CREATE_STAFF_CONTENT):
            lines.append(phrase("help", "staff_new_post"))
        if has_permission(user, Permission.MODERATE_CONTENT):
            lines.append(phrase("help", "staff_moderation"))
        if has_permission(user, Permission.MODERATE_ORDERS):
            lines.append(phrase("help", "staff_orders"))
        if has_permission(user, Permission.MANAGE_STAFF):
            lines.append(phrase("help", "staff_list"))
        if has_permission(user, Permission.MANAGE_SETTINGS):
            lines.append(phrase("help", "staff_settings"))
        if has_permission(user, Permission.MANAGE_SYSTEM):
            lines.append(phrase("help", "staff_reboot"))

    lines.extend(["", phrase("help", "hint")])
    return "\n".join(lines)
