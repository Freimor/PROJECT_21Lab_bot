from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

from lab21_bot.miniapp.deps import DbSession, MiniAppUser, SettingsDep, map_service_error
from lab21_bot.miniapp.serializers import join_application_to_dict, join_status_summary
from lab21_bot.models import JoinKind
from lab21_bot.services.admin_notify import notify_admin_event
from lab21_bot.services.applications import (
    ApplicationError,
    get_pending_application,
    submit_application,
)
from lab21_bot.services.chat_ui import normalize_bio

router = APIRouter(tags=["miniapp-join"])


class JoinApplicationBody(BaseModel):
    kind: JoinKind
    bio: str | None = None
    skills_text: str | None = None


@router.get("/join/status")
async def join_status(session: DbSession, user: MiniAppUser) -> dict:
    pending = await get_pending_application(session, user.telegram_id)
    return join_status_summary(pending, user)


@router.post("/join/applications")
async def create_join_application(
    body: JoinApplicationBody,
    session: DbSession,
    user: MiniAppUser,
    settings: SettingsDep,
) -> dict:
    if user.is_approved:
        raise map_service_error(ApplicationError("Вы уже участник"), forbidden=True)
    pending = await get_pending_application(session, user.telegram_id)
    if pending is not None:
        raise map_service_error(ApplicationError("Заявка уже ожидает решения"))
    bio = normalize_bio(body.bio) if body.bio else None
    skills_text = (body.skills_text or "").strip() or None
    if body.kind == JoinKind.COMMUNITY:
        if not bio:
            raise map_service_error(ApplicationError("Заполните «О себе»"))
        if not skills_text:
            raise map_service_error(ApplicationError("Опишите навыки"))
    try:
        application = await submit_application(
            session,
            user,
            body.kind,
            expire_days=settings.application_expire_days,
            bio=bio,
            skills_text=skills_text,
        )
    except ApplicationError as exc:
        raise map_service_error(exc) from exc

    kind_label = "послушник" if body.kind == JoinKind.COMMUNITY else "сотрудник"
    notify_body = (
        f"Тип: {kind_label}\n"
        f"{user.full_name}"
        + (f" (@{user.username})" if user.username else "")
        + f"\nID: {user.telegram_id}\n"
        f"Заявка #{application.id}\n"
    )
    if bio:
        notify_body += f"О себе: {bio}\n"
    if skills_text:
        notify_body += f"Навыки (текст): {skills_text}\n"
    notify_body += f"Автоотказ: {application.expires_at:%d.%m.%Y}"

    await notify_admin_event(
        session,
        settings,
        "join_community" if body.kind == JoinKind.COMMUNITY else "join_staff",
        title="Новая заявка на вступление",
        body=notify_body,
        link="/community",
    )
    return join_application_to_dict(application)
