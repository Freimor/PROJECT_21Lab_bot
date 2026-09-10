from __future__ import annotations

from fastapi import APIRouter, UploadFile
from pydantic import BaseModel, Field

from lab21_bot.data import setting_default
from lab21_bot.miniapp.deps import ApprovedUser, DbSession, SettingsDep, map_service_error
from lab21_bot.miniapp.serializers import content_to_dict
from lab21_bot.models import ContentItem, ContentKind
from lab21_bot.services.admin_notify import notify_admin_event
from lab21_bot.services.content import ContentError, submit_community_content
from lab21_bot.services.memes import MemeError
from lab21_bot.services.settings import get_int_setting
from lab21_bot.services.uploads import UploadError, save_image
from sqlalchemy import select

router = APIRouter(tags=["miniapp-submissions"])


class PostSubmissionBody(BaseModel):
    kind: ContentKind
    source_text: str = Field(min_length=1)


@router.get("/submissions/topics")
async def submission_topics(_user: ApprovedUser) -> dict:
    return {
        "topics": [
            {"id": "story", "title": "История / пост"},
            {"id": "meme", "title": "Мем"},
        ]
    }


@router.get("/submissions/mine")
async def my_submissions(session: DbSession, user: ApprovedUser) -> dict:
    items = await session.scalars(
        select(ContentItem)
        .where(ContentItem.author_id == user.telegram_id)
        .order_by(ContentItem.created_at.desc())
        .limit(50)
    )
    return {"items": [content_to_dict(item) for item in items]}


@router.post("/submissions/posts")
async def submit_post(
    body: PostSubmissionBody,
    session: DbSession,
    user: ApprovedUser,
    settings: SettingsDep,
) -> dict:
    try:
        item = await submit_community_content(
            session,
            user,
            body.kind,
            body.source_text,
        )
    except ContentError as exc:
        raise map_service_error(exc) from exc
    await notify_admin_event(
        session,
        settings,
        "content_queue",
        title="Новая публикация",
        body=f"{user.full_name}: {body.kind.value}",
        link="/publications",
    )
    return content_to_dict(item)


@router.post("/submissions/memes")
async def submit_meme_submission(
    session: DbSession,
    user: ApprovedUser,
    settings: SettingsDep,
    file: UploadFile,
    caption: str = "",
) -> dict:
    memes_enabled = await get_int_setting(
        session, "memes_enabled", setting_default("memes_enabled")
    )
    if not memes_enabled:
        raise map_service_error(MemeError("Приём мемов отключён"))
    try:
        rel_path = await save_image(
            settings.upload_dir,
            subdir="memes",
            entity_id=user.telegram_id,
            upload=file,
        )
    except UploadError as exc:
        raise map_service_error(exc) from exc
    media = [{"type": "photo", "path": rel_path}]
    text = caption.strip() or "(фото)"
    try:
        item = await submit_community_content(
            session,
            user,
            ContentKind.MEME,
            text,
            media=media,
        )
    except ContentError as exc:
        raise map_service_error(exc) from exc
    await notify_admin_event(
        session,
        settings,
        "content_queue",
        title=f"Новый мем #{item.id}",
        body=f"От {user.full_name} — в очереди модерации.",
        link="/publications/memes",
    )
    return content_to_dict(item)
