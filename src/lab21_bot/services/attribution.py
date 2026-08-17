from __future__ import annotations

import html
import re
from typing import TYPE_CHECKING

from lab21_bot.data import rank_label, respect_prefix, role_label

if TYPE_CHECKING:
    from lab21_bot.models import User

_SIGNATURE_TAIL = re.compile(r"(?:\r?\n){1,2}—[^\n]*\s*$")


def strip_author_signature(text: str) -> str:
    return _SIGNATURE_TAIL.sub("", text).strip()


def author_title_for_user(user: User) -> str:
    """Role label for staff; respect-prefix + community rank for members."""
    if user.staff_role is not None:
        return role_label(str(user.staff_role)).lower()
    prefix = respect_prefix(int(user.respect or 0))
    rank = rank_label(str(user.rank)).lower()
    return f"{prefix} {rank}"


def format_author_footer_html(
    *,
    author_name: str | None = None,
    author_username: str | None = None,
    title: str | None = None,
) -> str:
    """Telegram HTML attribution: — <i>Name</i> | title (no @username — avoids pings)."""
    del author_username  # kept for call-site compatibility; never rendered
    name = (author_name or "").strip() or "System"
    safe_name = html.escape(name)
    parts = [f"— <i>{safe_name}</i>"]
    clean_title = (title or "").strip()
    if clean_title:
        parts.append(html.escape(clean_title))
    if len(parts) == 1:
        return parts[0]
    return " | ".join(parts)


def format_author_footer_for_user(user: User) -> str:
    return format_author_footer_html(
        author_name=user.full_name,
        author_username=user.username,
        title=author_title_for_user(user),
    )


def append_author_footer_html(text: str, user: User | None) -> str:
    body = strip_author_signature(text)
    if user is None:
        footer = format_author_footer_html(author_name="System")
    else:
        footer = format_author_footer_for_user(user)
    if not body:
        return footer
    return f"{body}\n\n{footer}"
