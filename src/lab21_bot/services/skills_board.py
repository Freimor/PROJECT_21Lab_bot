"""Skill discovery board for community members."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from lab21_bot.data import list_skills, skill_title
from lab21_bot.models import User


async def members_with_skill(
    session: AsyncSession,
    skill_id: str,
    *,
    limit: int = 10,
) -> list[User]:
    rows = list(
        await session.scalars(
            select(User).where(
                User.is_approved.is_(True),
                User.is_active.is_(True),
                User.staff_role.is_(None),
            )
        )
    )
    matched = [user for user in rows if skill_id in set(user.skill_ids or [])]
    matched.sort(key=lambda u: (u.full_name or "").lower())
    return matched[:limit]


def format_skill_board(skill_id: str, members: list[User]) -> str:
    title = skill_title(skill_id)
    if not members:
        return f"Навык «{title}»: пока никого."
    lines = [f"Кто умеет «{title}»:"]
    for user in members:
        if user.username:
            lines.append(f"• @{user.username} — {user.full_name}")
        else:
            lines.append(f"• {user.full_name} (id {user.telegram_id})")
    return "\n".join(lines)


def skill_board_choices() -> list[tuple[str, str]]:
    return [(str(item["id"]), str(item.get("title") or item["id"])) for item in list_skills()]
