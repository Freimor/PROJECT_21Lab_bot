from __future__ import annotations

from fastapi import APIRouter

from lab21_bot.miniapp.deps import ApprovedUser, DbSession
from lab21_bot.services.skills_board import format_skill_board, members_with_skill
from lab21_bot.data import list_skills

router = APIRouter(tags=["miniapp-skills"])


@router.get("/skills/board")
async def skills_board(session: DbSession, _user: ApprovedUser) -> dict:
    return {
        "skills": [
            {"id": str(item["id"]), "title": str(item.get("title") or item["id"])}
            for item in list_skills()
        ]
    }


@router.get("/skills/board/{skill_id}")
async def skill_board_detail(skill_id: str, session: DbSession, _user: ApprovedUser) -> dict:
    members = await members_with_skill(session, skill_id)
    text = format_skill_board(skill_id, members)
    return {
        "skill_id": skill_id,
        "members": [
            {
                "telegram_id": member.telegram_id,
                "full_name": member.full_name,
                "username": member.username,
            }
            for member in members
        ],
        "text": text,
    }
