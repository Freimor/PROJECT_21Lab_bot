from __future__ import annotations

from datetime import datetime
from typing import Annotated
from urllib.parse import quote
from zoneinfo import ZoneInfo
import json

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession

from lab21_bot.admin.deps import (
    CurrentUser,
    DbSession,
    RequireManageSettings,
    RequireModerateContent,
    SettingsDep,
)
from lab21_bot.admin.templating import render
from lab21_bot.config import Settings
from lab21_bot.data import setting_default
from lab21_bot.models import ContentItem, ContentKind, ContentTemplate, TemplateKind
from lab21_bot.services.access import Permission, has_permission
from lab21_bot.services.admin_notify import notify_admin_event
from lab21_bot.services.content import (
    KIND_LABELS,
    ContentError,
    cancel_schedule,
    list_moderation_queue,
    list_scheduled,
    mark_llm_draft,
    publication_stats,
    publish_content_item,
    reject_content,
    schedule_content,
    update_draft_text,
)
from lab21_bot.services.destinations import flood_destination
from lab21_bot.services.flood import maybe_send_flood_teaser
from lab21_bot.services.llm_config import get_llm_runtime
from lab21_bot.llm.client import LLMClient, LLMError
from lab21_bot.services.memes import (
    MemeError,
    approve_meme_to_collection,
    list_meme_applications,
    message_meme_approved,
    message_meme_rejected,
    post_collection_meme_now,
    reject_meme_application,
)
from lab21_bot.services.notify import notify_telegram_user
from lab21_bot.services.settings import SettingError, get_int_setting, set_int_setting
from lab21_bot.services.telegram_profile import TelegramProfileError, download_telegram_file
from lab21_bot.services.templates import (
    TemplateError,
    create_meme_collection,
    create_template,
    delete_meme_collection,
    delete_template,
    list_meme_collection,
    list_meme_collections,
    list_teaser_collection,
    update_template,
)

router = APIRouter(tags=["publications"])


async def _load_pub_settings(session: AsyncSession, settings: Settings) -> dict[str, int]:
    return {
        "content_silence_days": await get_int_setting(
            session, "content_silence_days", settings.content_silence_days
        ),
        "reminder_hour": await get_int_setting(session, "reminder_hour", settings.reminder_hour),
        "memes_enabled": await get_int_setting(
            session, "memes_enabled", setting_default("memes_enabled")
        ),
        "interview_enabled": await get_int_setting(
            session, "interview_enabled", setting_default("interview_enabled")
        ),
        "teasers_enabled": await get_int_setting(
            session, "teasers_enabled", setting_default("teasers_enabled")
        ),
        "meme_interval_hours": await get_int_setting(
            session, "meme_interval_hours", setting_default("meme_interval_hours")
        ),
    }


def _redirect(
    path: str = "/publications",
    message: str | None = None,
    error: str | None = None,
) -> RedirectResponse:
    if "#" in path:
        base, fragment = path.split("#", 1)
        fragment = f"#{fragment}"
    else:
        base, fragment = path, ""
    if error:
        return RedirectResponse(f"{base}?error={quote(error)}{fragment}", status_code=303)
    return RedirectResponse(f"{base}?message={quote(message or 'Готово')}{fragment}", status_code=303)


def _pub_nav(user: CurrentUser) -> dict[str, bool]:
    return {
        "can_settings": has_permission(user, Permission.MANAGE_SETTINGS),
        "can_queue": has_permission(user, Permission.MODERATE_CONTENT),
    }


@router.get("/publications", response_class=HTMLResponse)
@router.get("/moderation", response_class=HTMLResponse)
async def publications_page(
    request: Request,
    session: DbSession,
    settings: SettingsDep,
    user: CurrentUser,
) -> HTMLResponse:
    nav = _pub_nav(user)
    if not nav["can_settings"] and not nav["can_queue"]:
        return RedirectResponse("/", status_code=303)
    items = await list_moderation_queue(session) if nav["can_queue"] else []
    scheduled = await list_scheduled(session) if nav["can_queue"] else []
    stats = await publication_stats(session, settings.main_channel_id)
    return await render(
        request,
        "publications.html",
        user=user,
        session=session,
        pub_section="queue",
        items=items,
        scheduled=scheduled,
        stats=stats,
        kind_labels={k.value: v for k, v in KIND_LABELS.items()},
        timezone=settings.timezone,
        **nav,
        message=request.query_params.get("message"),
        error=request.query_params.get("error"),
    )


@router.get("/publications/settings", response_class=HTMLResponse)
async def publications_settings_page(
    request: Request,
    session: DbSession,
    settings: SettingsDep,
    user: CurrentUser,
) -> HTMLResponse:
    if not has_permission(user, Permission.MANAGE_SETTINGS):
        return RedirectResponse("/publications", status_code=303)
    pub_settings = await _load_pub_settings(session, settings)
    return await render(
        request,
        "publications_settings.html",
        user=user,
        session=session,
        pub_section="settings",
        pub_settings=pub_settings,
        reminder_window_start=settings.reminder_window_start,
        reminder_window_end=settings.reminder_window_end,
        **_pub_nav(user),
        message=request.query_params.get("message"),
        error=request.query_params.get("error"),
    )


@router.get("/publications/templates", response_class=HTMLResponse)
async def publications_templates_redirect() -> RedirectResponse:
    return RedirectResponse("/publications/teasers", status_code=303)


@router.get("/publications/teasers", response_class=HTMLResponse)
async def publications_teasers_page(
    request: Request,
    session: DbSession,
    user: CurrentUser,
) -> HTMLResponse:
    if not has_permission(user, Permission.MANAGE_SETTINGS):
        return RedirectResponse("/publications", status_code=303)
    sort = request.query_params.get("sort", "desc")
    newest_first = sort != "asc"
    teasers = await list_teaser_collection(session, newest_first=newest_first)
    return await render(
        request,
        "publications_teasers.html",
        user=user,
        session=session,
        pub_section="teasers",
        teasers=teasers,
        newest_first=newest_first,
        **_pub_nav(user),
        message=request.query_params.get("message"),
        error=request.query_params.get("error"),
    )


@router.get("/publications/memes", response_class=HTMLResponse)
async def publications_memes_page(
    request: Request,
    session: DbSession,
    user: CurrentUser,
) -> HTMLResponse:
    nav = _pub_nav(user)
    if not nav["can_settings"] and not nav["can_queue"]:
        return RedirectResponse("/", status_code=303)
    sort = request.query_params.get("sort", "asc")
    reactions_asc = sort != "desc"
    collection_filter = (request.query_params.get("collection") or "").strip() or None
    applications = await list_meme_applications(session) if nav["can_queue"] else []
    collection = await list_meme_collection(
        session,
        reactions_asc=reactions_asc,
        collection_key=collection_filter,
    )
    collections = await list_meme_collections(session)
    collection_keys = [item.key for item in collections]
    return await render(
        request,
        "publications_memes.html",
        user=user,
        session=session,
        pub_section="memes",
        applications=applications,
        collection=collection,
        collections=collections,
        collection_keys=collection_keys,
        collection_keys_json=json.dumps(collection_keys, ensure_ascii=False),
        collection_filter=collection_filter or "",
        reactions_asc=reactions_asc,
        **nav,
        message=request.query_params.get("message"),
        error=request.query_params.get("error"),
    )


async def _proxy_media_file(
    settings: Settings,
    media: list[dict] | None,
    index: int,
) -> Response:
    items = media or []
    if index < 0 or index >= len(items):
        return Response(status_code=404)
    entry = items[index]
    file_id = entry.get("file_id") if isinstance(entry, dict) else None
    if not file_id:
        return Response(status_code=404)
    try:
        content, content_type = await download_telegram_file(
            settings.telegram_bot_token.get_secret_value(),
            str(file_id),
        )
    except TelegramProfileError:
        return Response(status_code=404)
    return Response(
        content=content,
        media_type=content_type,
        headers={"Cache-Control": "private, max-age=3600"},
    )


@router.get("/publications/memes/applications/{item_id}/media/{index}")
async def meme_application_media(
    item_id: int,
    index: int,
    session: DbSession,
    settings: SettingsDep,
    user: CurrentUser,
) -> Response:
    nav = _pub_nav(user)
    if not nav["can_queue"] and not nav["can_settings"]:
        return Response(status_code=403)
    item = await session.get(ContentItem, item_id)
    if item is None or item.kind is not ContentKind.MEME:
        return Response(status_code=404)
    return await _proxy_media_file(settings, item.media, index)


@router.get("/publications/{item_id}/media/{index}")
async def publication_application_media(
    item_id: int,
    index: int,
    session: DbSession,
    settings: SettingsDep,
    user: CurrentUser,
) -> Response:
    nav = _pub_nav(user)
    if not nav["can_queue"] and not nav["can_settings"]:
        return Response(status_code=403)
    item = await session.get(ContentItem, item_id)
    if item is None or item.kind not in {ContentKind.STORY, ContentKind.IMPORTANT}:
        return Response(status_code=404)
    return await _proxy_media_file(settings, item.media, index)


@router.get("/publications/memes/collection/{template_id}/media/{index}")
async def meme_collection_media(
    template_id: int,
    index: int,
    session: DbSession,
    settings: SettingsDep,
    user: CurrentUser,
) -> Response:
    nav = _pub_nav(user)
    if not nav["can_queue"] and not nav["can_settings"]:
        return Response(status_code=403)
    template = await session.get(ContentTemplate, template_id)
    if template is None or template.kind is not TemplateKind.MEME:
        return Response(status_code=404)
    return await _proxy_media_file(settings, template.media, index)


@router.post("/publications/memes/create")
async def publications_meme_create(
    session: DbSession,
    actor: RequireManageSettings,
    body: Annotated[str, Form()],
    title: Annotated[str, Form()] = "",
    collection_key: Annotated[str, Form()] = "default",
) -> RedirectResponse:
    try:
        await create_template(
            session,
            actor,
            TemplateKind.MEME,
            body,
            title=title or None,
            author_id=None,
            collection_key=collection_key or "default",
        )
        return _redirect("/publications/memes", "Мем добавлен в коллекцию")
    except TemplateError as exc:
        return _redirect("/publications/memes", error=str(exc))


@router.post("/publications/settings")
async def publications_save_settings(
    session: DbSession,
    settings: SettingsDep,
    actor: RequireManageSettings,
    content_silence_days: Annotated[int, Form()],
    reminder_hour: Annotated[int, Form()],
    meme_interval_hours: Annotated[int, Form()] = 6,
    memes_enabled: Annotated[str, Form()] = "0",
    interview_enabled: Annotated[str, Form()] = "0",
    teasers_enabled: Annotated[str, Form()] = "0",
) -> RedirectResponse:
    try:
        if not (settings.reminder_window_start <= reminder_hour < settings.reminder_window_end):
            raise SettingError(
                f"Час напоминания: {settings.reminder_window_start}–"
                f"{settings.reminder_window_end - 1}"
            )
        await set_int_setting(session, actor, "content_silence_days", content_silence_days)
        await set_int_setting(session, actor, "reminder_hour", reminder_hour)
        await set_int_setting(session, actor, "meme_interval_hours", meme_interval_hours)
        await set_int_setting(
            session, actor, "memes_enabled", 1 if memes_enabled in {"1", "on", "true"} else 0
        )
        await set_int_setting(
            session,
            actor,
            "interview_enabled",
            1 if interview_enabled in {"1", "on", "true"} else 0,
        )
        await set_int_setting(
            session, actor, "teasers_enabled", 1 if teasers_enabled in {"1", "on", "true"} else 0
        )
        return _redirect("/publications/settings", "Настройки сохранены")
    except SettingError as exc:
        return _redirect("/publications/settings", error=str(exc))


@router.post("/publications/{item_id}/generate")
async def publications_generate_llm(
    item_id: int,
    session: DbSession,
    settings: SettingsDep,
    reviewer: RequireModerateContent,
) -> RedirectResponse:
    try:
        from lab21_bot.models import ContentItem, ContentKind, ContentStatus

        item = await session.get(ContentItem, item_id)
        if item is None or item.kind not in {ContentKind.STORY, ContentKind.IMPORTANT}:
            raise ContentError("Материал не найден")
        if item.status is not ContentStatus.MODERATION:
            raise ContentError("Генерация только из очереди модерации")
        source = item.source_text
        interview = source.lstrip().startswith("Q:")
        job = source.lstrip().startswith("JOB:")
        client = LLMClient(settings)
        try:
            runtime = await get_llm_runtime(session, settings)
            draft = await client.generate_staff_post(
                source, interview=interview, job=job, runtime=runtime
            )
        finally:
            await client.close()
        await mark_llm_draft(session, item_id, draft, reviewer=reviewer)
        await notify_admin_event(
            session,
            settings,
            "llm_done",
            title=f"LLM-черновик готов #{item_id}",
            body="Проверьте перед публикацией.",
            link=f"/publications#item-{item_id}",
        )
        return _redirect(
            f"/publications#item-{item_id}",
            message=f"LLM-черновик готов #{item_id} — проверьте перед публикацией",
        )
    except (ContentError, LLMError) as exc:
        return _redirect(f"/publications#item-{item_id}", error=str(exc))


@router.post("/publications/{item_id}/publish")
async def publications_publish_now(
    item_id: int,
    session: DbSession,
    settings: SettingsDep,
    reviewer: RequireModerateContent,
    draft_text: Annotated[str, Form()] = "",
) -> RedirectResponse:
    try:
        token = settings.telegram_bot_token.get_secret_value()
        item = await publish_content_item(
            session,
            token,
            settings,
            item_id,
            reviewer=reviewer,
            draft_text=draft_text or None,
        )
        await maybe_send_flood_teaser(
            session,
            token,
            flood_destination(settings),
            item,
            item.author,
            story_thread_id=settings.main_thread_id,
        )
        return _redirect(message=f"Опубликовано #{item_id}")
    except ContentError as exc:
        return _redirect(error=str(exc))


@router.post("/publications/{item_id}/schedule")
async def publications_schedule(
    item_id: int,
    session: DbSession,
    settings: SettingsDep,
    reviewer: RequireModerateContent,
    scheduled_at: Annotated[str, Form()] = "",
    draft_text: Annotated[str, Form()] = "",
) -> RedirectResponse:
    if not scheduled_at.strip():
        return _redirect(error="Укажите дату и время для планирования")
    try:
        tz = ZoneInfo(settings.timezone)
        local = datetime.fromisoformat(scheduled_at)
        if local.tzinfo is None:
            local = local.replace(tzinfo=tz)
        await schedule_content(
            session,
            reviewer,
            item_id,
            local.astimezone(ZoneInfo("UTC")),
            draft_text=draft_text or None,
        )
        return _redirect(message=f"Запланировано #{item_id}")
    except (ContentError, ValueError) as exc:
        return _redirect(error=str(exc) if str(exc) else "Укажите дату и время")


@router.post("/publications/{item_id}/reject")
async def publications_reject(
    item_id: int,
    session: DbSession,
    settings: SettingsDep,
    reviewer: RequireModerateContent,
    note: Annotated[str, Form()] = "",
) -> RedirectResponse:
    try:
        from lab21_bot.services.user_messages import message_content_rejected

        item = await reject_content(session, reviewer, item_id, note=note.strip() or None)
        token = settings.telegram_bot_token.get_secret_value()
        await notify_telegram_user(
            token,
            item.author_id,
            message_content_rejected(note=note, reviewer=reviewer),
            parse_mode="HTML",
        )
        return _redirect(message=f"Отклонено #{item_id}")
    except ContentError as exc:
        return _redirect(error=str(exc))


@router.post("/publications/{item_id}/save-draft")
async def publications_save_draft(
    item_id: int,
    session: DbSession,
    reviewer: RequireModerateContent,
    draft_text: Annotated[str, Form()],
) -> RedirectResponse:
    try:
        await update_draft_text(session, reviewer, item_id, draft_text)
        return _redirect(message="Черновик сохранён")
    except ContentError as exc:
        return _redirect(error=str(exc))


@router.post("/publications/{item_id}/cancel-schedule")
async def publications_cancel_schedule(
    item_id: int,
    session: DbSession,
    reviewer: RequireModerateContent,
) -> RedirectResponse:
    try:
        await cancel_schedule(session, reviewer, item_id)
        return _redirect(message="Снято с расписания")
    except ContentError as exc:
        return _redirect(error=str(exc))


@router.post("/publications/templates/create")
@router.post("/publications/teasers/create")
async def publications_teaser_create(
    session: DbSession,
    actor: RequireManageSettings,
    body: Annotated[str, Form()],
    title: Annotated[str, Form()] = "",
) -> RedirectResponse:
    try:
        await create_template(
            session,
            actor,
            TemplateKind.FLOOD_TEASER,
            body,
            title=title or None,
        )
        return _redirect("/publications/teasers", "Тизер добавлен")
    except (TemplateError, ValueError) as exc:
        return _redirect("/publications/teasers", error=str(exc))


@router.post("/publications/templates/{template_id}/update")
@router.post("/publications/teasers/{template_id}/update")
async def publications_teaser_update(
    template_id: int,
    session: DbSession,
    actor: RequireManageSettings,
    body: Annotated[str, Form()],
    is_active: Annotated[str, Form()] = "0",
    title: Annotated[str, Form()] = "",
) -> RedirectResponse:
    try:
        await update_template(
            session,
            actor,
            template_id,
            body=body,
            title=title or None,
            is_active=is_active in {"1", "on", "true"},
        )
        return _redirect("/publications/teasers", "Тизер обновлён")
    except TemplateError as exc:
        return _redirect("/publications/teasers", error=str(exc))


@router.post("/publications/templates/{template_id}/delete")
@router.post("/publications/teasers/{template_id}/delete")
async def publications_teaser_delete(
    template_id: int,
    session: DbSession,
    actor: RequireManageSettings,
) -> RedirectResponse:
    try:
        await delete_template(session, actor, template_id)
        return _redirect("/publications/teasers", "Тизер удалён")
    except TemplateError as exc:
        return _redirect("/publications/teasers", error=str(exc))


@router.post("/publications/memes/{item_id}/approve")
async def publications_meme_approve(
    item_id: int,
    session: DbSession,
    settings: SettingsDep,
    reviewer: RequireModerateContent,
    title: Annotated[str, Form()] = "",
    collection_key: Annotated[str, Form()] = "default",
) -> RedirectResponse:
    try:
        item, _template = await approve_meme_to_collection(
            session,
            reviewer,
            item_id,
            title=title or None,
            collection_key=collection_key or "default",
        )
        token = settings.telegram_bot_token.get_secret_value()
        await notify_telegram_user(token, item.author_id, message_meme_approved())
        try:
            from lab21_bot.services.flavor import maybe_send_flavor
            from aiogram import Bot

            bot = Bot(token)
            try:
                await maybe_send_flavor(
                    bot,
                    event_key="meme_approved",
                    user_id=item.author_id,
                    session=session,
                )
            finally:
                await bot.session.close()
        except Exception:
            pass
        return _redirect("/publications/memes", f"Мем #{item_id} добавлен в коллекцию")
    except (MemeError, ContentError) as exc:
        return _redirect("/publications/memes", error=str(exc))


@router.post("/publications/memes/{item_id}/reject")
async def publications_meme_reject(
    item_id: int,
    session: DbSession,
    settings: SettingsDep,
    reviewer: RequireModerateContent,
    note: Annotated[str, Form()] = "",
) -> RedirectResponse:
    try:
        item = await reject_meme_application(
            session, reviewer, item_id, note=note.strip() or None
        )
        token = settings.telegram_bot_token.get_secret_value()
        await notify_telegram_user(
            token,
            item.author_id,
            message_meme_rejected(note=note, reviewer=reviewer),
            parse_mode="HTML",
        )
        return _redirect("/publications/memes", f"Мем #{item_id} отклонён")
    except MemeError as exc:
        return _redirect("/publications/memes", error=str(exc))


@router.post("/publications/memes/collections/create")
async def publications_meme_collection_create(
    session: DbSession,
    actor: RequireManageSettings,
    key: Annotated[str, Form()],
) -> RedirectResponse:
    try:
        row = await create_meme_collection(session, actor, key)
        return _redirect("/publications/memes", f"Коллекция «{row.key}» создана")
    except TemplateError as exc:
        return _redirect("/publications/memes", error=str(exc))


@router.post("/publications/memes/collections/{key}/delete")
async def publications_meme_collection_remove(
    key: str,
    session: DbSession,
    actor: RequireManageSettings,
    move_to: Annotated[str, Form()] = "",
) -> RedirectResponse:
    try:
        moved = await delete_meme_collection(
            session,
            actor,
            key,
            move_to=move_to.strip() or None,
        )
        if moved:
            return _redirect(
                "/publications/memes",
                f"Коллекция «{key}» удалена, мемов перенесено: {moved}",
            )
        return _redirect("/publications/memes", f"Коллекция «{key}» удалена")
    except TemplateError as exc:
        return _redirect("/publications/memes", error=str(exc))


@router.post("/publications/memes/collection/{template_id}/move")
async def publications_meme_move(
    template_id: int,
    session: DbSession,
    actor: RequireManageSettings,
    collection_key: Annotated[str, Form()] = "default",
) -> RedirectResponse:
    try:
        await update_template(
            session,
            actor,
            template_id,
            collection_key=collection_key or "default",
        )
        return _redirect("/publications/memes", "Коллекция обновлена")
    except TemplateError as exc:
        return _redirect("/publications/memes", error=str(exc))


@router.post("/publications/memes/collection/{template_id}/post-now")
async def publications_meme_post_now(
    template_id: int,
    session: DbSession,
    settings: SettingsDep,
    actor: RequireManageSettings,
) -> RedirectResponse:
    flood = flood_destination(settings)
    if flood is None:
        return _redirect("/publications/memes", error="Флудилка не настроена")
    try:
        item = await post_collection_meme_now(
            session,
            actor,
            template_id,
            bot_token=settings.telegram_bot_token.get_secret_value(),
            chat_id=flood.chat_id,
            message_thread_id=flood.thread_id,
            fallback_author_id=settings.bootstrap_magister_id,
        )
        return _redirect("/publications/memes", f"Мем запощен (#{item.id})")
    except MemeError as exc:
        return _redirect("/publications/memes", error=str(exc))


@router.post("/publications/memes/collection/{template_id}/delete")
async def publications_meme_collection_delete(
    template_id: int,
    session: DbSession,
    actor: RequireManageSettings,
) -> RedirectResponse:
    try:
        await delete_template(session, actor, template_id)
        return _redirect("/publications/memes", "Мем удалён из коллекции")
    except TemplateError as exc:
        return _redirect("/publications/memes", error=str(exc))


@router.post("/moderation/{item_id}/decide")
async def legacy_decide(
    item_id: int,
    session: DbSession,
    settings: SettingsDep,
    reviewer: RequireModerateContent,
    decision: Annotated[str, Form()],
    note: Annotated[str, Form()] = "",
    edited_text: Annotated[str, Form()] = "",
) -> RedirectResponse:
    if decision == "reject":
        return await publications_reject(item_id, session, settings, reviewer, note)
    if decision == "approve":
        return await publications_publish_now(item_id, session, settings, reviewer, edited_text)
    try:
        from lab21_bot.models import ContentStatus
        from lab21_bot.services.content import moderate_content

        await moderate_content(
            session,
            reviewer,
            item_id,
            ContentStatus.NEEDS_INFO,
            edited_text=edited_text.strip() or None,
            note=note.strip() or None,
        )
        return _redirect(message="Запрошена доработка")
    except ContentError as exc:
        return _redirect(error=str(exc))
