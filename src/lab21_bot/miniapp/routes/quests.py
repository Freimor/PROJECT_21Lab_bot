from __future__ import annotations

import uuid

from fastapi import APIRouter
from pydantic import BaseModel, Field
from sqlalchemy import select

from lab21_bot.miniapp.deps import ApprovedUser, DbSession, map_service_error
from lab21_bot.models import CommunityQuest, CommunityQuestStatus
from lab21_bot.services.quests import QuestError, get_quest, join_quest, leave_quest, list_quests, user_open_quest_memberships

router = APIRouter(tags=["miniapp-quests"])


def quest_to_dict(quest: CommunityQuest) -> dict:
    status = quest.status.value if hasattr(quest.status, "value") else quest.status
    return {
        "id": quest.id,
        "title": quest.title,
        "description": quest.description,
        "status": status,
        "reward": quest.reward,
        "member_limit": quest.member_limit,
        "starts_at": quest.starts_at.isoformat() if quest.starts_at else None,
        "ends_at": quest.ends_at.isoformat() if quest.ends_at else None,
    }


@router.get("/quests")
async def quests_list(session: DbSession, user: ApprovedUser) -> dict:
    open_quests = await list_quests(session, status=CommunityQuestStatus.OPEN)
    mine = await user_open_quest_memberships(session, user.telegram_id)
    mine_ids = {quest.id for quest in mine}
    return {
        "quests": [
            {**quest_to_dict(quest), "joined": quest.id in mine_ids}
            for quest in open_quests
        ],
        "mine": [quest_to_dict(quest) for quest in mine],
    }


@router.post("/quests/{quest_id}/join")
async def quest_join(quest_id: int, session: DbSession, user: ApprovedUser) -> dict:
    quest = await get_quest(session, quest_id)
    try:
        await join_quest(session, quest, user)
    except QuestError as exc:
        raise map_service_error(exc) from exc
    return {"ok": True}


@router.post("/quests/{quest_id}/leave")
async def quest_leave(quest_id: int, session: DbSession, user: ApprovedUser) -> dict:
    try:
        await leave_quest(session, quest_id, user.telegram_id)
    except QuestError as exc:
        raise map_service_error(exc) from exc
    return {"ok": True}
