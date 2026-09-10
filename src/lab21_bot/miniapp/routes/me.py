from __future__ import annotations

import uuid

from fastapi import APIRouter
from pydantic import BaseModel, Field

from lab21_bot.data import list_skills
from lab21_bot.miniapp.deps import ApprovedUser, DbSession, MiniAppUser, SettingsDep, map_service_error
from lab21_bot.miniapp.serializers import join_status_summary, user_to_dict
from lab21_bot.services.applications import ApplicationError, remove_member_skill, request_member_skill
from lab21_bot.services.chat_ui import normalize_bio
from lab21_bot.services.content import count_user_publications
from lab21_bot.services.economy import EconomyError, history, transfer
from lab21_bot.services.applications import get_pending_application
from lab21_bot.services.ritual import RitualError, perform_ritual
from lab21_bot.services.settings import get_int_setting

router = APIRouter(tags=["miniapp-me"])


class MePatch(BaseModel):
    bio: str | None = None
    job_notify_enabled: bool | None = None


class TransferBody(BaseModel):
    recipient_id: int
    amount: int = Field(gt=0)
    reason: str = "перевод"


class SkillToggle(BaseModel):
    skill_id: str


@router.get("/me")
async def get_me(session: DbSession, user: MiniAppUser) -> dict:
    pending = await get_pending_application(session, user.telegram_id)
    posts = await count_user_publications(session, user.telegram_id)
    payload = user_to_dict(user)
    payload["publications_count"] = posts
    payload["join"] = join_status_summary(pending, user)
    return payload


@router.patch("/me")
async def patch_me(body: MePatch, session: DbSession, user: MiniAppUser) -> dict:
    if body.bio is not None:
        user.bio = normalize_bio(body.bio)
    if body.job_notify_enabled is not None:
        user.job_notify_enabled = body.job_notify_enabled
    await session.flush()
    return user_to_dict(user)


@router.get("/me/skills/catalog")
async def skills_catalog(_user: MiniAppUser) -> dict:
    return {
        "skills": [
            {
                "id": str(item["id"]),
                "title": str(item.get("title") or item["id"]),
                "requires_validation": bool(item.get("requires_validation")),
                "grace_price": int(item.get("grace_price") or 0),
            }
            for item in list_skills()
        ]
    }


@router.post("/me/skills")
async def add_skill(body: SkillToggle, session: DbSession, user: ApprovedUser) -> dict:
    try:
        await request_member_skill(session, user, body.skill_id)
    except ApplicationError as exc:
        raise map_service_error(exc) from exc
    await session.refresh(user)
    return user_to_dict(user)


@router.delete("/me/skills/{skill_id}")
async def remove_skill(skill_id: str, session: DbSession, user: ApprovedUser) -> dict:
    try:
        await remove_member_skill(session, user, skill_id)
    except ApplicationError as exc:
        raise map_service_error(exc) from exc
    await session.refresh(user)
    return user_to_dict(user)


@router.get("/balance")
async def get_balance(session: DbSession, user: ApprovedUser) -> dict:
    posts = await count_user_publications(session, user.telegram_id)
    return {
        "balance": user.balance,
        "respect": user.respect,
        "rank": user.rank.value if hasattr(user.rank, "value") else user.rank,
        "publications_count": posts,
    }


@router.get("/history")
async def get_history(session: DbSession, user: ApprovedUser) -> dict:
    entries = await history(session, user.telegram_id)
    return {
        "entries": [
            {
                "created_at": entry.created_at.isoformat(),
                "delta": entry.delta,
                "reason": entry.reason,
                "type": entry.type.value if hasattr(entry.type, "value") else entry.type,
            }
            for entry in entries
        ]
    }


@router.post("/transfers")
async def create_transfer(
    body: TransferBody,
    session: DbSession,
    user: ApprovedUser,
    settings: SettingsDep,
) -> dict:
    daily_limit = await get_int_setting(
        session,
        "transfer_daily_limit",
        settings.transfer_daily_limit,
    )
    try:
        await transfer(
            session,
            user.telegram_id,
            body.recipient_id,
            body.amount,
            body.reason,
            daily_limit,
            idempotency_key=f"miniapp:{uuid.uuid4()}",
        )
    except EconomyError as exc:
        raise map_service_error(exc) from exc
    await session.refresh(user)
    return {"balance": user.balance}


@router.post("/ritual/bow")
async def ritual_bow(session: DbSession, user: ApprovedUser, settings: SettingsDep) -> dict:
    if user.staff_role is not None:
        raise map_service_error(RitualError("Ритуал только для участников"), forbidden=True)
    try:
        result = await perform_ritual(session, user, tz=settings.tz)
    except RitualError as exc:
        raise map_service_error(exc) from exc
    await session.refresh(user)
    return {
        "message": result.message,
        "streak": result.streak,
        "balance": user.balance,
    }
