"""Community quests posted to «Важное»."""

from __future__ import annotations

from datetime import UTC, date, datetime
from html import escape
from pathlib import Path
from typing import Any

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest, TelegramForbiddenError
from aiogram.types import FSInputFile, InlineKeyboardMarkup, InputMediaPhoto, Message
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from lab21_bot.data import phrase, skill_title
from lab21_bot.keyboards import quest_card_keyboard
from lab21_bot.models import (
    CommunityQuest,
    CommunityQuestMember,
    CommunityQuestStatus,
    ContentKind,
    LedgerType,
    User,
)
from lab21_bot.services.access import Permission, require_permission
from lab21_bot.services.destinations import DestinationError, destination_for_kind
from lab21_bot.services.economy import EconomyError, reward_participant

_CAPTION_LIMIT = 1024


class QuestError(RuntimeError):
    pass


def _quest_reply_markup(quest: CommunityQuest, *, completed: bool = False, joined: bool = False):
    if completed or quest.status is not CommunityQuestStatus.OPEN:
        return InlineKeyboardMarkup(inline_keyboard=[])
    return quest_card_keyboard(quest.id, joined=joined)


async def next_quest_number(session: AsyncSession) -> int:
    current = await session.scalar(select(func.max(CommunityQuest.number)))
    return int(current or 0) + 1


def format_quest_schedule(quest: CommunityQuest) -> str | None:
    start = quest.quest_date
    end = quest.quest_ends_on
    if start is None and end is None:
        return "Бессрочный"
    if start is not None and end is None:
        end = start
    if end is not None and start is None:
        start = end
    assert start is not None and end is not None
    if start == end:
        return f"Дата: {start.isoformat()}"
    return f"Даты: {start.isoformat()} — {end.isoformat()}"


def validate_quest_schedule(
    *,
    quest_date: date | None,
    quest_ends_on: date | None,
) -> tuple[date | None, date | None]:
    if quest_date is None and quest_ends_on is None:
        return None, None
    if quest_date is None or quest_ends_on is None:
        raise QuestError("Укажи начало и конец периода или выбери «Бессрочный»")
    if quest_ends_on < quest_date:
        raise QuestError("Конец периода не может быть раньше начала")
    return quest_date, quest_ends_on


def format_quest_html(quest: CommunityQuest, members: list[User]) -> str:
    skills = ", ".join(escape(skill_title(sid)) for sid in (quest.skill_ids or [])) or "—"
    lines = [
        f"<b>Квест #{quest.number}: {escape(quest.title)}</b>",
    ]
    schedule = format_quest_schedule(quest)
    if schedule:
        lines.append(schedule)
    lines.append("")
    lines.append(escape(quest.description))
    lines.append("")
    lines.append(f"Навыки: {skills}")
    lines.append(f"Максимум участников: {quest.required_participants}")
    lines.append(f"Награда: {quest.grace_reward} 🙏 / {quest.respect_reward} ❇")
    lines.append("")
    if members:
        handles = []
        for user in members:
            handles.append(escape(user.full_name))
        lines.append("Участвуют: " + ", ".join(handles))
    else:
        lines.append("Участвуют: —")
    return "\n".join(lines)


def format_quest_completed_html(quest: CommunityQuest) -> str:
    return phrase(
        "quests",
        "completed_public",
        number=quest.number,
        title=escape(quest.title),
    )


def quest_image_item(quest: CommunityQuest) -> dict[str, Any] | None:
    media = list(quest.media or [])
    if not media:
        return None
    item = media[0]
    if item.get("type") != "photo":
        return None
    if not item.get("path") and not item.get("file_id"):
        return None
    return item


def quest_has_image(quest: CommunityQuest) -> bool:
    return quest_image_item(quest) is not None


def quest_image_path(quest: CommunityQuest) -> str | None:
    item = quest_image_item(quest)
    if item is None:
        return None
    path = item.get("path")
    return str(path) if path else None


def fit_quest_caption(html: str, limit: int = _CAPTION_LIMIT) -> str:
    if len(html) <= limit:
        return html
    return html[: max(0, limit - 1)] + "…"


def media_photo_entry(*, path: str | None = None, file_id: str | None = None) -> dict[str, Any]:
    entry: dict[str, Any] = {"type": "photo"}
    if path:
        entry["path"] = path
    if file_id:
        entry["file_id"] = file_id
    return entry


def _telegram_not_modified(exc: BaseException) -> bool:
    return "not modified" in str(exc).lower()


def _photo_input(item: dict[str, Any], upload_dir: str | Path | None) -> str | FSInputFile:
    file_id = item.get("file_id")
    if file_id:
        return str(file_id)
    path = item.get("path")
    if not path or not upload_dir:
        raise QuestError("Нет файла изображения квеста")
    full = Path(upload_dir) / str(path)
    if not full.is_file():
        raise QuestError("Файл изображения квеста не найден")
    return FSInputFile(full)


async def send_quest_post(
    bot: Bot,
    *,
    chat_id: int,
    html: str,
    quest: CommunityQuest,
    upload_dir: str | Path | None = None,
    message_thread_id: int | None = None,
    reply_markup: Any = None,
) -> Message:
    thread_kwargs = (
        {"message_thread_id": message_thread_id} if message_thread_id is not None else {}
    )
    markup = (
        reply_markup
        if reply_markup is not None
        else _quest_reply_markup(quest)
    )
    item = quest_image_item(quest)
    if item is not None:
        photo = _photo_input(item, upload_dir)
        sent = await bot.send_photo(
            chat_id,
            photo,
            caption=fit_quest_caption(html),
            parse_mode="HTML",
            reply_markup=markup,
            **thread_kwargs,
        )
        if sent.photo:
            item = {**item, "file_id": sent.photo[-1].file_id}
            quest.media = [item]
        return sent
    return await bot.send_message(
        chat_id,
        html,
        parse_mode="HTML",
        reply_markup=markup,
        **thread_kwargs,
    )


async def edit_quest_post_html(
    bot: Bot,
    quest: CommunityQuest,
    html: str,
    *,
    reply_markup: Any = None,
    completed: bool = False,
    joined: bool | None = None,
) -> bool:
    """Edit the public quest message. Returns True if Telegram accepted the edit."""
    if not quest.chat_id or not quest.message_id:
        return False
    chat_id = quest.chat_id
    message_id = quest.message_id
    markup = (
        reply_markup
        if reply_markup is not None
        else _quest_reply_markup(
            quest,
            completed=completed,
            joined=bool(joined),
        )
    )
    extra = {"reply_markup": markup}

    async def _try_caption() -> bool:
        try:
            await bot.edit_message_caption(
                chat_id=chat_id,
                message_id=message_id,
                caption=fit_quest_caption(html),
                parse_mode="HTML",
                **extra,
            )
            return True
        except (TelegramBadRequest, TelegramForbiddenError) as exc:
            return _telegram_not_modified(exc)

    async def _try_text() -> bool:
        try:
            await bot.edit_message_text(
                html,
                chat_id=chat_id,
                message_id=message_id,
                parse_mode="HTML",
                **extra,
            )
            return True
        except (TelegramBadRequest, TelegramForbiddenError) as exc:
            return _telegram_not_modified(exc)

    if quest_has_image(quest):
        return await _try_caption() or await _try_text()
    return await _try_text() or await _try_caption()


async def _resend_quest_post(
    bot: Bot,
    quest: CommunityQuest,
    html: str,
    *,
    upload_dir: str | Path | None = None,
    message_thread_id: int | None = None,
    reply_markup: Any = None,
) -> None:
    chat_id = quest.chat_id
    message_id = quest.message_id
    if chat_id and message_id:
        try:
            await bot.delete_message(chat_id=chat_id, message_id=message_id)
        except (TelegramBadRequest, TelegramForbiddenError):
            pass
    if not chat_id:
        raise QuestError("Нет чата для поста квеста")
    sent = await send_quest_post(
        bot,
        chat_id=chat_id,
        html=html,
        quest=quest,
        upload_dir=upload_dir,
        message_thread_id=message_thread_id,
        reply_markup=reply_markup,
    )
    quest.chat_id = sent.chat.id
    quest.message_id = sent.message_id


async def sync_quest_telegram_post(
    bot: Bot,
    quest: CommunityQuest,
    members: list[User],
    *,
    upload_dir: str | Path | None = None,
    message_thread_id: int | None = None,
    completed: bool = False,
    was_image: bool | None = None,
    media_changed: bool = False,
) -> None:
    """Update or replace the public quest message to match current fields/media."""
    if not quest.chat_id or not quest.message_id:
        return
    html = (
        format_quest_completed_html(quest)
        if completed
        else format_quest_html(quest, members)
    )
    wants_image = quest_has_image(quest)
    posted_as_image = was_image if was_image is not None else wants_image
    chat_id = quest.chat_id
    message_id = quest.message_id
    markup = _quest_reply_markup(quest, completed=completed)

    if wants_image == posted_as_image and not media_changed:
        if await edit_quest_post_html(
            bot, quest, html, reply_markup=markup, completed=completed
        ):
            return
        await _resend_quest_post(
            bot,
            quest,
            html,
            upload_dir=upload_dir,
            message_thread_id=message_thread_id,
            reply_markup=markup,
        )
        return

    if wants_image == posted_as_image and media_changed and wants_image:
        item = quest_image_item(quest)
        assert item is not None
        try:
            photo = _photo_input(item, upload_dir)
            await bot.edit_message_media(
                media=InputMediaPhoto(
                    media=photo,
                    caption=fit_quest_caption(html),
                    parse_mode="HTML",
                ),
                chat_id=chat_id,
                message_id=message_id,
                reply_markup=markup,
            )
            return
        except (TelegramBadRequest, TelegramForbiddenError) as exc:
            if _telegram_not_modified(exc):
                return

    await _resend_quest_post(
        bot,
        quest,
        html,
        upload_dir=upload_dir,
        message_thread_id=message_thread_id,
        reply_markup=markup,
    )


async def refresh_open_quest_posts(
    bot: Bot,
    session: AsyncSession,
    settings: Any,
) -> int:
    """Re-sync Telegram posts for all open quests. Returns how many were attempted."""
    try:
        dest = destination_for_kind(settings, ContentKind.IMPORTANT)
    except DestinationError:
        return 0
    quests = await list_quests(session, status=CommunityQuestStatus.OPEN)
    updated = 0
    for quest in quests:
        if not quest.chat_id or not quest.message_id:
            continue
        members = await quest_member_users(quest)
        try:
            await sync_quest_telegram_post(
                bot,
                quest,
                members,
                upload_dir=getattr(settings, "upload_dir", None),
                message_thread_id=dest.thread_id,
            )
        except (TelegramAPIError, QuestError):
            continue
        updated += 1
    return updated


async def create_quest(
    session: AsyncSession,
    actor: User,
    *,
    title: str,
    description: str,
    skill_ids: list[str],
    required_participants: int,
    grace_reward: int,
    respect_reward: int,
    quest_date: date | None = None,
    quest_ends_on: date | None = None,
    media: list[dict] | None = None,
) -> CommunityQuest:
    require_permission(actor, Permission.CREATE_STAFF_CONTENT)
    title = title.strip()
    description = description.strip()
    if not title or not description:
        raise QuestError("Название и описание обязательны")
    if required_participants < 1:
        raise QuestError("Нужен хотя бы один участник")
    if grace_reward < 0 or respect_reward < 0:
        raise QuestError("Награда не может быть отрицательной")
    start, end = validate_quest_schedule(quest_date=quest_date, quest_ends_on=quest_ends_on)

    quest = CommunityQuest(
        number=await next_quest_number(session),
        title=title[:200],
        description=description,
        media=media or [],
        skill_ids=list(skill_ids),
        required_participants=required_participants,
        grace_reward=grace_reward,
        respect_reward=respect_reward,
        status=CommunityQuestStatus.OPEN,
        created_by=actor.telegram_id,
        quest_date=start,
        quest_ends_on=end,
    )
    session.add(quest)
    await session.flush()
    return quest


async def update_quest(
    session: AsyncSession,
    actor: User,
    quest_id: int,
    *,
    title: str | None = None,
    description: str | None = None,
    skill_ids: list[str] | None = None,
    required_participants: int | None = None,
    grace_reward: int | None = None,
    respect_reward: int | None = None,
    quest_date: date | None = None,
    quest_ends_on: date | None = None,
    update_schedule: bool = False,
    media: list[dict] | None = None,
    clear_media: bool = False,
) -> CommunityQuest:
    require_permission(actor, Permission.CREATE_STAFF_CONTENT)
    quest = await get_quest(session, quest_id)
    if quest.status is not CommunityQuestStatus.OPEN:
        raise QuestError(phrase("quests", "closed"))
    if title is not None:
        clean = title.strip()
        if not clean:
            raise QuestError("Название обязательно")
        quest.title = clean[:200]
    if description is not None:
        clean = description.strip()
        if not clean:
            raise QuestError("Описание обязательно")
        quest.description = clean
    if skill_ids is not None:
        quest.skill_ids = list(skill_ids)
    if required_participants is not None:
        if required_participants < 1:
            raise QuestError("Нужен хотя бы один участник")
        quest.required_participants = required_participants
    if grace_reward is not None:
        if grace_reward < 0:
            raise QuestError("Награда не может быть отрицательной")
        quest.grace_reward = grace_reward
    if respect_reward is not None:
        if respect_reward < 0:
            raise QuestError("Награда не может быть отрицательной")
        quest.respect_reward = respect_reward
    if update_schedule:
        start, end = validate_quest_schedule(
            quest_date=quest_date,
            quest_ends_on=quest_ends_on,
        )
        quest.quest_date = start
        quest.quest_ends_on = end
    if clear_media:
        quest.media = []
    elif media is not None:
        quest.media = list(media)
    await session.flush()
    return await get_quest(session, quest_id)

async def get_open_quest_by_message(
    session: AsyncSession,
    *,
    chat_id: int,
    message_id: int,
    for_update: bool = False,
) -> CommunityQuest | None:
    query = select(CommunityQuest).where(
        CommunityQuest.chat_id == chat_id,
        CommunityQuest.message_id == message_id,
        CommunityQuest.status == CommunityQuestStatus.OPEN,
    )
    if for_update:
        query = query.with_for_update()
    return await session.scalar(query)


async def list_quests(
    session: AsyncSession,
    *,
    status: CommunityQuestStatus | None = None,
) -> list[CommunityQuest]:
    query = (
        select(CommunityQuest)
        .options(
            selectinload(CommunityQuest.members).selectinload(CommunityQuestMember.user),
            selectinload(CommunityQuest.creator),
        )
        .order_by(CommunityQuest.number.desc())
    )
    if status is not None:
        query = query.where(CommunityQuest.status == status)
    return list(await session.scalars(query))


async def get_quest(session: AsyncSession, quest_id: int) -> CommunityQuest:
    quest = await session.scalar(
        select(CommunityQuest)
        .options(
            selectinload(CommunityQuest.members).selectinload(CommunityQuestMember.user),
        )
        .where(CommunityQuest.id == quest_id)
    )
    if quest is None:
        raise QuestError("Квест не найден")
    return quest


async def join_quest(session: AsyncSession, quest: CommunityQuest, user: User) -> CommunityQuestMember:
    if quest.status is not CommunityQuestStatus.OPEN:
        raise QuestError(phrase("quests", "closed"))
    if user.staff_role is not None or not user.is_approved:
        raise QuestError(phrase("quests", "members_only"))

    existing = await session.scalar(
        select(CommunityQuestMember).where(
            CommunityQuestMember.quest_id == quest.id,
            CommunityQuestMember.user_id == user.telegram_id,
        )
    )
    if existing is not None:
        raise QuestError(phrase("quests", "already_joined"))

    required = set(quest.skill_ids or [])
    have = set(user.skill_ids or [])
    if required - have:
        raise QuestError(phrase("quests", "missing_skill_alert"))

    taken = await session.scalar(
        select(func.count())
        .select_from(CommunityQuestMember)
        .where(CommunityQuestMember.quest_id == quest.id)
    )
    if int(taken or 0) >= quest.required_participants:
        raise QuestError(phrase("quests", "full"))

    member = CommunityQuestMember(quest_id=quest.id, user_id=user.telegram_id)
    session.add(member)
    await session.flush()
    return member


async def leave_quest(session: AsyncSession, quest_id: int, user_id: int) -> CommunityQuest:
    quest = await get_quest(session, quest_id)
    if quest.status is not CommunityQuestStatus.OPEN:
        raise QuestError(phrase("quests", "closed"))
    member = await session.scalar(
        select(CommunityQuestMember).where(
            CommunityQuestMember.quest_id == quest_id,
            CommunityQuestMember.user_id == user_id,
        )
    )
    if member is None:
        raise QuestError(phrase("quests", "not_joined"))
    await session.delete(member)
    await session.flush()
    return await get_quest(session, quest_id)


async def staff_remove_member(
    session: AsyncSession,
    actor: User,
    quest_id: int,
    user_id: int,
) -> CommunityQuest:
    require_permission(actor, Permission.CREATE_STAFF_CONTENT)
    return await leave_quest(session, quest_id, user_id)


async def quest_member_users(quest: CommunityQuest) -> list[User]:
    return [m.user for m in (quest.members or []) if m.user is not None]


async def complete_quest(
    session: AsyncSession,
    actor: User,
    quest_id: int,
    shares: dict[int, float],
) -> CommunityQuest:
    """shares: user_id -> percent 0..100, must sum to ~100 if members exist."""
    require_permission(actor, Permission.MANAGE_ECONOMY)
    quest = await get_quest(session, quest_id)
    if quest.status is not CommunityQuestStatus.OPEN:
        raise QuestError(phrase("quests", "closed"))

    members = list(quest.members or [])
    if members:
        total_pct = sum(float(shares.get(m.user_id, 0)) for m in members)
        if abs(total_pct - 100.0) > 0.5:
            raise QuestError("Сумма долей должна быть 100%")

    for member in members:
        pct = float(shares.get(member.user_id, 0)) / 100.0
        grace = int(round(quest.grace_reward * pct))
        respect = int(round(quest.respect_reward * pct))
        member.reward_grace = grace
        member.reward_respect = respect
        if grace or respect:
            try:
                await reward_participant(
                    session,
                    member.user_id,
                    grace=grace,
                    respect=respect,
                    reason=f"Квест #{quest.number}: {quest.title}",
                    idempotency_key=f"quest:{quest.id}:user:{member.user_id}",
                    grace_entry_type=LedgerType.GRANT,
                )
            except EconomyError as exc:
                raise QuestError(str(exc)) from exc

    quest.status = CommunityQuestStatus.COMPLETED
    quest.completed_at = datetime.now(UTC)
    await session.flush()
    return quest


async def user_open_quest_memberships(
    session: AsyncSession, user_id: int
) -> list[CommunityQuest]:
    return list(
        await session.scalars(
            select(CommunityQuest)
            .join(CommunityQuestMember)
            .where(
                CommunityQuestMember.user_id == user_id,
                CommunityQuest.status == CommunityQuestStatus.OPEN,
            )
            .order_by(CommunityQuest.number.desc())
        )
    )
