from __future__ import annotations

from datetime import date
from typing import Annotated

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse

from lab21_bot.admin.deps import (
    CurrentUser,
    DbSession,
    RequireCreateStaffContent,
    RequireManageEconomy,
    RequireManageSettings,
    SettingsDep,
)
from lab21_bot.admin.templating import render
from lab21_bot.config import Settings
from lab21_bot.data import list_season_phrase_keys, list_skills, phrase, setting_default
from lab21_bot.models import AdminAction, CommunityQuestStatus, ContentKind
from lab21_bot.services.destinations import DestinationError, destination_for_kind
from lab21_bot.services.quests import (
    QuestError,
    complete_quest,
    create_quest,
    format_quest_html,
    get_quest,
    list_quests,
    media_photo_entry,
    quest_has_image,
    quest_image_path,
    quest_member_users,
    send_quest_post,
    staff_remove_member,
    sync_quest_telegram_post,
    update_quest,
)
from lab21_bot.services.seasons import (
    SeasonError,
    build_season_year_map,
    create_season,
    delete_season,
    get_season,
    list_seasons,
    update_season,
)
from lab21_bot.services.settings import SettingError, get_int_setting, set_int_setting
from lab21_bot.services.templates import MemeCollectionInfo, list_meme_collections
from lab21_bot.services.uploads import UploadError, save_quest_image
from lab21_bot.telegram_client import create_bot

router = APIRouter()

_GAME_SETTING_KEYS = (
    "ritual_grace",
    "ritual_streak_bonus_grace",
    "ritual_reply_ttl_seconds",
    "mention_cooldown_seconds",
    "bless_daily_limit",
    "bless_pair_cooldown_days",
    "flavor_chance_percent",
    "season_reminder_days",
)


def _bot(settings: Settings) -> Bot:
    return create_bot(settings)


def _redirect(path: str = "/gamification/quests", *, message: str = "", error: str = "") -> RedirectResponse:
    params: list[str] = []
    if message:
        params.append(f"message={message.replace(' ', '+')}")
    if error:
        params.append(f"error={error.replace(' ', '+')}")
    suffix = ("?" + "&".join(params)) if params else ""
    return RedirectResponse(f"{path}{suffix}", status_code=303)


def _parse_quest_schedule(
    schedule_mode: str,
    quest_date: str,
    quest_ends_on: str,
) -> tuple[date | None, date | None]:
    mode = schedule_mode.strip().lower()
    if mode in {"", "indefinite", "open", "none"}:
        return None, None
    start_raw = quest_date.strip()
    end_raw = quest_ends_on.strip() or start_raw
    if not start_raw:
        raise QuestError("Укажи начало и конец периода или выбери «Бессрочный»")
    start = date.fromisoformat(start_raw)
    end = date.fromisoformat(end_raw)
    if end < start:
        raise QuestError("Конец периода не может быть раньше начала")
    return start, end


async def _meme_collections_for_select(
    session: DbSession, current: str | None = None
) -> list[MemeCollectionInfo]:
    collections = await list_meme_collections(session)
    if current and current not in {item.key for item in collections}:
        collections = [*collections, MemeCollectionInfo(key=current, meme_count=0)]
    return collections


def _phrase_keys_for_select(current: str | None = None) -> list[dict[str, str | int]]:
    items = list_season_phrase_keys()
    if current and current not in {str(item["key"]) for item in items}:
        items = [*items, {"key": current, "phrase_count": 0}]
    return items


async def _sync_quest_post(
    settings: Settings,
    quest,
    members,
    *,
    was_image: bool | None = None,
    media_changed: bool = False,
    completed: bool = False,
) -> None:
    if not quest.chat_id or not quest.message_id:
        return
    bot = _bot(settings)
    try:
        dest = destination_for_kind(settings, ContentKind.IMPORTANT)
        await sync_quest_telegram_post(
            bot,
            quest,
            members,
            upload_dir=settings.upload_dir,
            message_thread_id=dest.thread_id,
            completed=completed,
            was_image=was_image,
            media_changed=media_changed,
        )
    except (TelegramAPIError, DestinationError) as exc:
        raise QuestError("Не удалось обновить пост в Telegram") from exc
    finally:
        await bot.session.close()


@router.get("/gamification", response_class=HTMLResponse)
async def gamification_home() -> RedirectResponse:
    return RedirectResponse("/gamification/quests", status_code=303)


@router.get("/gamification/quests", response_class=HTMLResponse)
async def gamification_quests_page(
    request: Request,
    user: CurrentUser,
    session: DbSession,
) -> HTMLResponse:
    quests = await list_quests(session)
    draft: dict = {}
    copy_id = request.query_params.get("copy")
    if copy_id and copy_id.isdigit():
        try:
            source = await get_quest(session, int(copy_id))
            draft = {
                "title": source.title,
                "description": source.description,
                "schedule_mode": "range" if source.quest_date or source.quest_ends_on else "indefinite",
                "quest_date": source.quest_date.isoformat() if source.quest_date else "",
                "quest_ends_on": (
                    source.quest_ends_on.isoformat()
                    if source.quest_ends_on
                    else (source.quest_date.isoformat() if source.quest_date else "")
                ),
                "required_participants": source.required_participants,
                "grace_reward": source.grace_reward,
                "respect_reward": source.respect_reward,
                "skill_ids": list(source.skill_ids or []),
            }
        except QuestError:
            draft = {}
    return await render(
        request,
        "gamification_quests.html",
        user=user,
        session=session,
        quests=quests,
        skills=list_skills(),
        draft=draft,
        message=request.query_params.get("message"),
        error=request.query_params.get("error"),
    )


@router.post("/gamification/quests")
async def gamification_quest_create(
    user: RequireCreateStaffContent,
    session: DbSession,
    settings: SettingsDep,
    title: str = Form(...),
    description: str = Form(...),
    required_participants: int = Form(1),
    grace_reward: int = Form(0),
    respect_reward: int = Form(0),
    schedule_mode: str = Form("indefinite"),
    quest_date: str = Form(""),
    quest_ends_on: str = Form(""),
    skill_ids: list[str] = Form(default=[]),
    image: Annotated[UploadFile | None, File()] = None,
) -> RedirectResponse:
    try:
        start, end = _parse_quest_schedule(schedule_mode, quest_date, quest_ends_on)
        quest = await create_quest(
            session,
            user,
            title=title,
            description=description,
            skill_ids=list(skill_ids),
            required_participants=required_participants,
            grace_reward=grace_reward,
            respect_reward=respect_reward,
            quest_date=start,
            quest_ends_on=end,
        )
        if image is not None and image.filename:
            path = await save_quest_image(settings.upload_dir, quest.id, image)
            quest.media = [media_photo_entry(path=path)]
            await session.flush()
        dest = destination_for_kind(settings, ContentKind.IMPORTANT)
        bot = _bot(settings)
        html = format_quest_html(quest, [])
        try:
            sent = await send_quest_post(
                bot,
                chat_id=dest.chat_id,
                html=html,
                quest=quest,
                upload_dir=settings.upload_dir,
                message_thread_id=dest.thread_id,
            )
            quest.chat_id = sent.chat.id
            quest.message_id = sent.message_id
        except TelegramAPIError as exc:
            await session.delete(quest)
            await session.flush()
            return _redirect(error=str(exc)[:120])
        finally:
            await bot.session.close()
        session.add(
            AdminAction(
                actor_id=user.telegram_id,
                action="create_quest",
                target_id=quest.id,
                details={"number": quest.number, "title": quest.title},
            )
        )
        await session.flush()
    except (QuestError, DestinationError, ValueError, UploadError) as exc:
        return _redirect(error=str(exc))
    return _redirect(message="Квест+создан")


@router.get("/gamification/quests/{quest_id}", response_class=HTMLResponse)
async def gamification_quest_detail(
    request: Request,
    user: CurrentUser,
    session: DbSession,
    quest_id: int,
) -> HTMLResponse:
    try:
        quest = await get_quest(session, quest_id)
    except QuestError:
        return _redirect(error="Квест+не+найден")
    return await render(
        request,
        "gamification_quest.html",
        user=user,
        session=session,
        quest=quest,
        quest_image=quest_image_path(quest),
        members=await quest_member_users(quest),
        skills=list_skills(),
        message=request.query_params.get("message"),
        error=request.query_params.get("error"),
    )


@router.post("/gamification/quests/{quest_id}/update")
async def gamification_quest_update(
    user: RequireCreateStaffContent,
    session: DbSession,
    settings: SettingsDep,
    quest_id: int,
    title: str = Form(...),
    description: str = Form(...),
    required_participants: int = Form(1),
    grace_reward: int = Form(0),
    respect_reward: int = Form(0),
    schedule_mode: str = Form("indefinite"),
    quest_date: str = Form(""),
    quest_ends_on: str = Form(""),
    skill_ids: list[str] = Form(default=[]),
    clear_image: str = Form(""),
    image: Annotated[UploadFile | None, File()] = None,
) -> RedirectResponse:
    try:
        existing = await get_quest(session, quest_id)
        was_image = quest_has_image(existing)
        start, end = _parse_quest_schedule(schedule_mode, quest_date, quest_ends_on)
        media_changed = False
        clear = clear_image.strip() in {"1", "true", "on", "yes"}
        new_media = None
        if image is not None and image.filename:
            path = await save_quest_image(settings.upload_dir, quest_id, image)
            new_media = [media_photo_entry(path=path)]
            media_changed = True
            clear = False
        elif clear:
            media_changed = was_image
        quest = await update_quest(
            session,
            user,
            quest_id,
            title=title,
            description=description,
            skill_ids=list(skill_ids),
            required_participants=required_participants,
            grace_reward=grace_reward,
            respect_reward=respect_reward,
            quest_date=start,
            quest_ends_on=end,
            update_schedule=True,
            media=new_media,
            clear_media=clear,
        )
        members = await quest_member_users(quest)
    except (QuestError, ValueError, UploadError) as exc:
        return _redirect(f"/gamification/quests/{quest_id}", error=str(exc))
    try:
        await _sync_quest_post(
            settings,
            quest,
            members,
            was_image=was_image,
            media_changed=media_changed,
        )
        await session.flush()
    except QuestError as exc:
        return _redirect(
            f"/gamification/quests/{quest_id}",
            message="Сохранено",
            error=str(exc),
        )
    return _redirect(f"/gamification/quests/{quest_id}", message="Сохранено.+Пост+обновлён")


@router.post("/gamification/quests/{quest_id}/remove-member")
async def gamification_quest_remove_member(
    user: RequireCreateStaffContent,
    session: DbSession,
    settings: SettingsDep,
    quest_id: int,
    member_id: int = Form(...),
) -> RedirectResponse:
    try:
        quest = await staff_remove_member(session, user, quest_id, member_id)
        members = await quest_member_users(quest)
        await _sync_quest_post(settings, quest, members)
    except QuestError as exc:
        return _redirect(f"/gamification/quests/{quest_id}", error=str(exc))
    return _redirect(f"/gamification/quests/{quest_id}")


@router.post("/gamification/quests/{quest_id}/refresh-post")
async def gamification_quest_refresh_post(
    user: RequireCreateStaffContent,
    session: DbSession,
    settings: SettingsDep,
    quest_id: int,
) -> RedirectResponse:
    try:
        quest = await get_quest(session, quest_id)
        members = await quest_member_users(quest)
        await _sync_quest_post(
            settings,
            quest,
            members,
            completed=quest.status != CommunityQuestStatus.OPEN,
        )
        await session.flush()
    except QuestError as exc:
        return _redirect(f"/gamification/quests/{quest_id}", error=str(exc))
    return _redirect(f"/gamification/quests/{quest_id}", message="Пост+обновлён")


@router.post("/gamification/quests/{quest_id}/complete")
async def gamification_quest_complete(
    request: Request,
    user: RequireManageEconomy,
    session: DbSession,
    settings: SettingsDep,
    quest_id: int,
) -> RedirectResponse:
    form = await request.form()
    shares: dict[int, float] = {}
    for key, value in form.items():
        if str(key).startswith("share_"):
            uid = int(str(key).removeprefix("share_"))
            try:
                shares[uid] = float(str(value))
            except ValueError:
                shares[uid] = 0.0
    try:
        quest = await complete_quest(session, user, quest_id, shares)
        members = await quest_member_users(quest)
        await _sync_quest_post(settings, quest, members, completed=True)
        session.add(
            AdminAction(
                actor_id=user.telegram_id,
                action="complete_quest",
                target_id=quest.id,
                details={"shares": shares},
            )
        )
    except QuestError as exc:
        return _redirect(f"/gamification/quests/{quest_id}", error=str(exc))
    return _redirect(message="Квест+завершён")


@router.get("/gamification/seasons", response_class=HTMLResponse)
async def gamification_seasons_page(
    request: Request,
    user: CurrentUser,
    session: DbSession,
) -> HTMLResponse:
    seasons = await list_seasons(session)
    today = date.today()
    year_raw = request.query_params.get("year", "")
    map_year = today.year
    if year_raw.isdigit():
        parsed_year = int(year_raw)
        if 2000 <= parsed_year <= 2100:
            map_year = parsed_year
    year_map = build_season_year_map(seasons, year=map_year, today=today)
    draft: dict = {}
    copy_id = request.query_params.get("copy")
    if copy_id and copy_id.isdigit():
        try:
            source = await get_season(session, int(copy_id))
            draft = {
                "code": f"{source.code}_copy",
                "title": source.title,
                "description": source.description,
                "starts_on": source.starts_on.isoformat(),
                "ends_on": source.ends_on.isoformat(),
                "meme_collection": source.meme_collection,
                "phrases_key": source.phrases_key,
                "start_message": source.start_message,
                "end_message": source.end_message,
            }
        except SeasonError:
            draft = {}
    return await render(
        request,
        "gamification_seasons.html",
        user=user,
        session=session,
        seasons=seasons,
        year_map=year_map,
        draft=draft,
        meme_collections=await _meme_collections_for_select(
            session, draft.get("meme_collection")
        ),
        phrase_keys=_phrase_keys_for_select(draft.get("phrases_key")),
        season_start_default=phrase("seasons", "start"),
        season_end_default=phrase("seasons", "end"),
        message=request.query_params.get("message"),
        error=request.query_params.get("error"),
    )


@router.get("/gamification/seasons/{season_id}", response_class=HTMLResponse)
async def gamification_season_detail(
    request: Request,
    user: CurrentUser,
    session: DbSession,
    season_id: int,
) -> HTMLResponse:
    try:
        season = await get_season(session, season_id)
    except SeasonError:
        return _redirect("/gamification/seasons", error="Сезон+не+найден")
    return await render(
        request,
        "gamification_season.html",
        user=user,
        session=session,
        season=season,
        meme_collections=await _meme_collections_for_select(
            session, season.meme_collection
        ),
        phrase_keys=_phrase_keys_for_select(season.phrases_key),
        season_start_default=phrase("seasons", "start"),
        season_end_default=phrase("seasons", "end"),
        message=request.query_params.get("message"),
        error=request.query_params.get("error"),
    )


@router.post("/gamification/seasons")
async def gamification_season_create(
    user: RequireManageSettings,
    session: DbSession,
    code: str = Form(...),
    title: str = Form(...),
    description: str = Form(""),
    starts_on: str = Form(...),
    ends_on: str = Form(...),
    meme_collection: str = Form("default"),
    phrases_key: str = Form(""),
    start_message: str = Form(""),
    end_message: str = Form(""),
) -> RedirectResponse:
    try:
        start = date.fromisoformat(starts_on)
        await create_season(
            session,
            user,
            code=code,
            title=title,
            description=description,
            starts_on=start,
            ends_on=date.fromisoformat(ends_on),
            meme_collection=meme_collection,
            phrases_key=phrases_key,
            start_message=start_message,
            end_message=end_message,
        )
        session.add(
            AdminAction(
                actor_id=user.telegram_id,
                action="create_season",
                details={"code": code, "title": title},
            )
        )
    except (SeasonError, ValueError) as exc:
        return _redirect("/gamification/seasons", error=str(exc))
    return _redirect(f"/gamification/seasons?year={start.year}", message="Сезон+создан")


@router.post("/gamification/seasons/{season_id}/update")
async def gamification_season_update(
    user: RequireManageSettings,
    session: DbSession,
    season_id: int,
    title: str = Form(...),
    description: str = Form(""),
    starts_on: str = Form(...),
    ends_on: str = Form(...),
    meme_collection: str = Form("default"),
    phrases_key: str = Form(""),
    start_message: str = Form(""),
    end_message: str = Form(""),
    is_enabled: str = Form("0"),
) -> RedirectResponse:
    try:
        await update_season(
            session,
            user,
            season_id,
            title=title,
            description=description,
            starts_on=date.fromisoformat(starts_on),
            ends_on=date.fromisoformat(ends_on),
            meme_collection=meme_collection,
            phrases_key=phrases_key,
            start_message=start_message,
            end_message=end_message,
            is_enabled=is_enabled in {"1", "true", "on"},
        )
    except (SeasonError, ValueError) as exc:
        return _redirect(f"/gamification/seasons/{season_id}", error=str(exc))
    return _redirect(f"/gamification/seasons/{season_id}", message="Сохранено")


@router.post("/gamification/seasons/{season_id}/delete")
async def gamification_season_delete(
    user: RequireManageSettings,
    session: DbSession,
    season_id: int,
) -> RedirectResponse:
    try:
        await delete_season(session, user, season_id)
    except SeasonError as exc:
        return _redirect("/gamification/seasons", error=str(exc))
    return _redirect("/gamification/seasons", message="Сезон+удалён")


@router.get("/gamification/settings", response_class=HTMLResponse)
async def gamification_settings_page(
    request: Request,
    user: CurrentUser,
    session: DbSession,
) -> HTMLResponse:
    settings_map = {
        key: await get_int_setting(session, key, int(setting_default(key)))
        for key in _GAME_SETTING_KEYS
    }
    return await render(
        request,
        "gamification_settings.html",
        user=user,
        session=session,
        settings_map=settings_map,
        message=request.query_params.get("message"),
        error=request.query_params.get("error"),
    )


@router.post("/gamification/settings")
async def gamification_settings_save(
    user: RequireManageSettings,
    session: DbSession,
    ritual_grace: int = Form(...),
    ritual_streak_bonus_grace: int = Form(...),
    ritual_reply_ttl_seconds: int = Form(...),
    mention_cooldown_seconds: int = Form(...),
    bless_daily_limit: int = Form(...),
    bless_pair_cooldown_days: int = Form(...),
    flavor_chance_percent: int = Form(...),
    season_reminder_days: int = Form(...),
) -> RedirectResponse:
    values = {
        "ritual_grace": ritual_grace,
        "ritual_streak_bonus_grace": ritual_streak_bonus_grace,
        "ritual_reply_ttl_seconds": ritual_reply_ttl_seconds,
        "mention_cooldown_seconds": mention_cooldown_seconds,
        "bless_daily_limit": bless_daily_limit,
        "bless_pair_cooldown_days": bless_pair_cooldown_days,
        "flavor_chance_percent": flavor_chance_percent,
        "season_reminder_days": season_reminder_days,
    }
    try:
        for key, value in values.items():
            await set_int_setting(session, user, key, value)
    except SettingError as exc:
        return _redirect("/gamification/settings", error=str(exc))
    return _redirect("/gamification/settings", message="Сохранено")
