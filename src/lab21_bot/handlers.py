from __future__ import annotations

import asyncio
from collections import defaultdict
from datetime import UTC, datetime
from html import escape
from typing import Any

import structlog
from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.filters import Command, CommandStart, ExceptionTypeFilter, Filter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    ErrorEvent,
    InputMediaDocument,
    InputMediaPhoto,
    InputMediaVideo,
    Message,
    MessageReactionCountUpdated,
    MessageReactionUpdated,
    ReplyKeyboardRemove,
)
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from lab21_bot.config import Settings
from lab21_bot.data import (
    format_skills_price_lines,
    phrase,
    setting_default,
    skill_title,
)
from lab21_bot.keyboards import (
    ROLE_LABELS,
    add_skill_keyboard,
    back_keyboard,
    cancel_writing_keyboard,
    content_actions,
    job_notify_keyboard,
    job_result_review_keyboard,
    my_jobs_keyboard,
    my_quests_keyboard,
    onboarding_keyboard,
    order_actions,
    profile_menu_keyboard,
    profile_skills_keyboard,
    shop_confirm_keyboard,
    shop_qty_keyboard,
    skill_board_keyboard,
    skill_toggle_keyboard,
    staff_menu,
    reboot_confirm_keyboard,
    with_back,
)
from lab21_bot.middlewares import DeleteCommandMessageMiddleware
from lab21_bot.llm.client import LLMClient, LLMError
from lab21_bot.models import (
    CommunityRank,
    ContentItem,
    ContentKind,
    ContentStatus,
    Interview,
    JoinKind,
    Order,
    OrderStatus,
    Product,
    ProductKind,
    ServiceJobStatus,
    StaffRole,
    User,
)
from lab21_bot.services.access import (
    AccessDenied,
    Permission,
    has_permission,
    list_staff,
    register_user,
    require_approved,
    require_approved_user,
    require_permission,
    set_staff_role,
)
from lab21_bot.services.admin_notify import notify_admin_event
from lab21_bot.services.applications import (
    ApplicationError,
    get_pending_application,
    remove_member_skill,
    request_member_skill,
    submit_application,
)
from lab21_bot.services.chat_ui import (
    delete_ids,
    delete_quietly,
    normalize_bio,
    profile_card_html,
    send_profile_card,
    status_text,
    upsert_status_card,
)
from lab21_bot.services.commands import sync_user_commands
from lab21_bot.services.content import (
    ContentError,
    count_user_publications,
    format_interview_source,
    list_moderation_queue,
    mark_llm_draft,
    moderate_content,
    publish_content_item,
    record_channel_post,
    submit_community_content,
    submit_for_moderation,
)
from lab21_bot.services.destinations import (
    flood_destination,
    job_destination,
    matches_bugs_destination,
    matches_destination,
)
from lab21_bot.services.feedback import (
    REACTION_PENDING,
    clean_feedback_text,
    create_feedback_report,
    detect_feedback_kind,
    media_from_telegram_message,
)
from lab21_bot.services.economy import (
    EconomyError,
    change_balance,
    change_respect,
    history,
    transfer,
)
from lab21_bot.services.flood import maybe_send_flood_teaser
from lab21_bot.services.help import build_help_text
from lab21_bot.services.job_publish import (
    notify_job_subscribers,
    publish_service_job,
    sync_job_board_post,
)
from lab21_bot.services.shop_publish import (
    html_user_mention,
    product_is_available,
    shop_order_preview,
    sync_shop_card,
    telegram_alert_text,
)
from lab21_bot.services.jobs import (
    JobError,
    claim_service_job,
    confirm_job_result,
    count_assignee_done_jobs,
    create_service_job,
    default_job_respect,
    get_job,
    get_job_by_order_id,
    list_assignee_claimed_jobs,
    min_job_price,
    reject_job_result,
    submit_job_result,
)
from lab21_bot.services.lifecycle import (
    LifecycleError,
    check_github_updates,
    request_restart,
)
from lab21_bot.services.llm_config import get_llm_runtime
from lab21_bot.services.reactions import apply_post_reaction_delta, sync_post_reaction_total
from lab21_bot.services.settings import SettingError, get_int_setting, set_int_setting
from lab21_bot.services.staff_chat import invite_to_staff_chat, kick_from_staff_chat
from lab21_bot.services.store import (
    count_user_product_qty,
    create_product,
    purchase,
    resolve_order,
    update_product,
)
from lab21_bot.services.user_messages import (
    message_content_rejected,
    message_order_cancelled,
    message_order_fulfilled,
    message_staff_role_cleared,
    message_staff_role_set,
)
from lab21_bot.services.bless import BlessError, bless_member
from lab21_bot.services.flavor import maybe_send_flavor
from lab21_bot.services.presence import (
    cooldown_remaining,
    message_mentions_bot,
    pick_mention_reply,
    set_cooldown,
)
from lab21_bot.services.quests import (
    QuestError,
    edit_quest_post_html,
    format_quest_html,
    join_quest,
    leave_quest,
    quest_member_users,
    user_open_quest_memberships,
)
from lab21_bot.services.ritual import RitualError, perform_ritual
from lab21_bot.services.seasons import active_season
from lab21_bot.services.skills_board import format_skill_board, members_with_skill


class SubmissionState(StatesGroup):
    meme = State()


class EditContentState(StatesGroup):
    text = State()


class ServiceJobState(StatesGroup):
    description = State()
    skill = State()
    price = State()
    assignee_note = State()


class JobResultState(StatesGroup):
    report = State()


class JoinState(StatesGroup):
    bio = State()
    skills = State()


class ProfileState(StatesGroup):
    bio = State()


class PostComposeState(StatesGroup):
    interview = State()


_log = structlog.get_logger(__name__)


async def _reply_job_thread(
    bot: Bot,
    event: MessageReactionUpdated,
    text: str,
    *,
    fallback_thread_id: int | None = None,
) -> bool:
    """Post feedback next to the job message (visible even when DM is closed)."""
    thread_id = event.message_thread_id
    if thread_id is None:
        thread_id = fallback_thread_id
    thread_kwargs: dict[str, Any] = {}
    if thread_id is not None:
        thread_kwargs["message_thread_id"] = thread_id
    try:
        await bot.send_message(
            event.chat.id,
            text,
            reply_to_message_id=event.message_id,
            **thread_kwargs,
        )
        return True
    except (TelegramBadRequest, TelegramForbiddenError):
        try:
            await bot.send_message(event.chat.id, text, **thread_kwargs)
            return True
        except (TelegramBadRequest, TelegramForbiddenError):
            return False


async def _dm_or_thread(
    bot: Bot,
    event: MessageReactionUpdated,
    user_id: int,
    text: str,
    *,
    fallback_thread_id: int | None = None,
) -> None:
    try:
        await bot.send_message(user_id, text)
    except (TelegramBadRequest, TelegramForbiddenError):
        await _reply_job_thread(
            bot,
            event,
            text,
            fallback_thread_id=fallback_thread_id,
        )


async def _send_private(bot: Bot, user_id: int, text: str) -> bool:
    try:
        await bot.send_message(user_id, text)
        return True
    except (TelegramBadRequest, TelegramForbiddenError):
        return False


ROLE_ALIASES = {
    "lord": StaffRole.LORD,
    "лорд": StaffRole.LORD,
    "magister": StaffRole.MAGISTER,
    "магистр": StaffRole.MAGISTER,
    "tech_priest": StaffRole.TECH_PRIEST,
    "техножрец": StaffRole.TECH_PRIEST,
    "watcher": StaffRole.WATCHER,
    "смотрящий": StaffRole.WATCHER,
    "none": None,
    "нет": None,
}


class AlbumCollector:
    def __init__(self) -> None:
        self.messages: dict[str, list[Message]] = defaultdict(list)
        self.lock = asyncio.Lock()

    async def collect(self, message: Message) -> list[Message] | None:
        if not message.media_group_id:
            return [message]
        async with self.lock:
            first = message.media_group_id not in self.messages
            self.messages[message.media_group_id].append(message)
        if not first:
            return None
        await asyncio.sleep(0.8)
        async with self.lock:
            return self.messages.pop(message.media_group_id, [])


def _media_from_messages(messages: list[Message]) -> list[dict[str, Any]]:
    media: list[dict[str, Any]] = []
    for message in messages:
        if message.photo:
            media.append({"type": "photo", "file_id": message.photo[-1].file_id})
        elif message.animation:
            media.append({"type": "animation", "file_id": message.animation.file_id})
        elif message.video:
            media.append({"type": "video", "file_id": message.video.file_id})
        elif message.document:
            media.append({"type": "document", "file_id": message.document.file_id})
    return media


def _is_gif_document(message: Message) -> bool:
    doc = message.document
    if doc is None:
        return False
    mime = (doc.mime_type or "").lower()
    name = (doc.file_name or "").lower()
    return mime == "image/gif" or name.endswith(".gif")


def _meme_payload_from_messages(
    messages: list[Message],
) -> tuple[str, list[dict[str, Any]]] | None:
    """Accept text and/or photos/GIFs. Reject video, non-gif docs, stickers, etc."""
    text = (
        next(
            (item.caption or item.text for item in messages if item.caption or item.text),
            "",
        )
        or ""
    ).strip()
    media: list[dict[str, Any]] = []
    for message in messages:
        if message.photo:
            media.append({"type": "photo", "file_id": message.photo[-1].file_id})
            continue
        if message.animation:
            media.append({"type": "animation", "file_id": message.animation.file_id})
            continue
        if message.document and _is_gif_document(message):
            media.append({"type": "document", "file_id": message.document.file_id})
            continue
        if message.text and not (
            message.photo
            or message.video
            or message.document
            or message.animation
            or message.sticker
            or message.voice
            or message.video_note
            or message.audio
        ):
            continue
        return None
    if not text and not media:
        return None
    return text, media


def _can_propose_important(user: User) -> bool:
    return user.staff_role in {StaffRole.LORD, StaffRole.MAGISTER}


def _thread_kwargs(message: Message) -> dict[str, int]:
    thread_id = message.message_thread_id
    if thread_id is None:
        return {}
    return {"message_thread_id": thread_id}


async def _publish_item(
    bot: Bot,
    channel_id: int,
    item: ContentItem,
    *,
    message_thread_id: int | None = None,
) -> int:
    text = item.draft_text or item.source_text
    thread_kwargs = (
        {"message_thread_id": message_thread_id} if message_thread_id is not None else {}
    )
    parse_kwargs: dict[str, str] = {}
    if item.kind in {ContentKind.STORY, ContentKind.IMPORTANT}:
        parse_kwargs["parse_mode"] = "HTML"
    if not item.media:
        sent = await bot.send_message(channel_id, text, **thread_kwargs, **parse_kwargs)
        return sent.message_id
    caption = text if len(text) <= 1024 else None
    if len(item.media) == 1:
        media = item.media[0]
        if media["type"] == "photo":
            sent = await bot.send_photo(
                channel_id,
                media["file_id"],
                caption=caption,
                **thread_kwargs,
                **(parse_kwargs if caption else {}),
            )
        elif media["type"] == "animation":
            sent = await bot.send_animation(
                channel_id,
                media["file_id"],
                caption=caption,
                **thread_kwargs,
                **(parse_kwargs if caption else {}),
            )
        elif media["type"] == "video":
            sent = await bot.send_video(
                channel_id,
                media["file_id"],
                caption=caption,
                **thread_kwargs,
                **(parse_kwargs if caption else {}),
            )
        else:
            sent = await bot.send_document(
                channel_id,
                media["file_id"],
                caption=caption,
                **thread_kwargs,
                **(parse_kwargs if caption else {}),
            )
        if caption is None:
            text_message = await bot.send_message(
                channel_id, text, **thread_kwargs, **parse_kwargs
            )
            return text_message.message_id
        return sent.message_id

    # Albums: Telegram media groups don't reliably mix animations — send GIFs
    # as documents so the group stays valid.
    telegram_media: list[InputMediaPhoto | InputMediaVideo | InputMediaDocument] = []
    for index, media in enumerate(item.media):
        item_caption = caption if index == 0 else None
        caption_kwargs = parse_kwargs if item_caption else {}
        if media["type"] == "photo":
            telegram_media.append(
                InputMediaPhoto(
                    media=media["file_id"], caption=item_caption, **caption_kwargs
                )
            )
        elif media["type"] == "video":
            telegram_media.append(
                InputMediaVideo(
                    media=media["file_id"], caption=item_caption, **caption_kwargs
                )
            )
        else:
            telegram_media.append(
                InputMediaDocument(
                    media=media["file_id"], caption=item_caption, **caption_kwargs
                )
            )
    sent_group = await bot.send_media_group(
        channel_id,
        telegram_media,  # type: ignore[arg-type]
        **thread_kwargs,
    )
    if caption is None:
        text_message = await bot.send_message(
            channel_id, text, **thread_kwargs, **parse_kwargs
        )
        return text_message.message_id
    return sent_group[0].message_id


async def _send_review_item(bot: Bot, chat_id: int, item: ContentItem) -> None:
    await _publish_item(bot, chat_id, item)
    await bot.send_message(
        chat_id,
        f"Действия с материалом #{item.id}:",
        reply_markup=content_actions(item),
    )


def create_router(
    settings: Settings,
    factory: async_sessionmaker[AsyncSession],
    llm: LLMClient,
) -> Router:
    router = Router(name="lab21")
    router.message.middleware(DeleteCommandMessageMiddleware())
    albums = AlbumCollector()

    class FeedbackIntakeFilter(Filter):
        """Match /bug and /upgrade in the bugs topic (including album follow-ups)."""

        async def __call__(self, message: Message) -> bool:
            thread_id = getattr(message, "message_thread_id", None)
            if not matches_bugs_destination(
                settings, chat_id=message.chat.id, thread_id=thread_id
            ):
                return False
            if detect_feedback_kind(message.text or message.caption) is not None:
                return True
            return bool(message.media_group_id)

    class BotMentionedFilter(Filter):
        async def __call__(self, message: Message, bot: Bot) -> bool:
            me = await bot.get_me()
            username = settings.telegram_bot_username or me.username
            return message_mentions_bot(
                message, bot_id=me.id, bot_username=username
            )

    class ForumTopicTrackedFilter(Filter):
        async def __call__(self, message: Message) -> bool:
            chat_id = message.chat.id
            thread_id = message.message_thread_id
            return matches_destination(
                settings,
                chat_id=chat_id,
                thread_id=thread_id,
                kind=ContentKind.STORY,
            ) or matches_destination(
                settings,
                chat_id=chat_id,
                thread_id=thread_id,
                kind=ContentKind.IMPORTANT,
            )

    @router.error(ExceptionTypeFilter(AccessDenied))
    async def access_denied(event: ErrorEvent, bot: Bot) -> None:
        text = str(event.exception)
        update = event.update
        if update.callback_query is not None:
            await update.callback_query.answer(text, show_alert=True)
            if text == phrase("onboarding", "need_apply") and update.callback_query.from_user:
                try:
                    await bot.send_message(
                        update.callback_query.from_user.id,
                        phrase("onboarding", "choose_path"),
                        reply_markup=onboarding_keyboard(),
                    )
                except (TelegramBadRequest, TelegramForbiddenError):
                    pass
            return
        if update.message is not None:
            await update.message.answer(text)
            if text == phrase("onboarding", "need_apply") and update.message.from_user:
                try:
                    await bot.send_message(
                        update.message.from_user.id,
                        phrase("onboarding", "choose_path"),
                        reply_markup=onboarding_keyboard(),
                    )
                except (TelegramBadRequest, TelegramForbiddenError):
                    pass

    async def current_user(session: AsyncSession, telegram_id: int) -> User:
        user = await session.get(User, telegram_id)
        if user is None:
            raise AccessDenied("Сначала запустите бота командой /start")
        return await require_approved_user(session, user)

    async def refresh_home(bot: Bot, telegram_id: int, *, markup=None) -> None:
        async with factory.begin() as session:
            user = await session.get(User, telegram_id)
            if user is None or not user.is_approved:
                return
            await upsert_status_card(bot, session, user, markup=markup)

    def _writing_states() -> set[str]:
        return {
            PostComposeState.interview.state,
            SubmissionState.meme.state,
            EditContentState.text.state,
            JoinState.bio.state,
            JoinState.skills.state,
            ProfileState.bio.state,
            ServiceJobState.description.state,
            ServiceJobState.skill.state,
            ServiceJobState.price.state,
            ServiceJobState.assignee_note.state,
            JobResultState.report.state,
        }

    def _order_states() -> set[str]:
        return {
            ServiceJobState.description.state,
            ServiceJobState.skill.state,
            ServiceJobState.price.state,
            ServiceJobState.assignee_note.state,
            JobResultState.report.state,
        }

    async def _is_writing(state: FSMContext) -> bool:
        current = await state.get_state()
        return current in _writing_states()

    async def _cancel_prompt_text(state: FSMContext) -> str:
        current = await state.get_state()
        if current in _order_states():
            return "Отменить заказ?"
        if current == SubmissionState.meme.state:
            return "Отменить отправку мема?"
        if current in {JoinState.bio.state, JoinState.skills.state}:
            return "Отменить заполнение заявки?"
        if current == ProfileState.bio.state:
            return "Отменить изменение «О себе»?"
        if current == EditContentState.text.state:
            return "Отменить редактирование?"
        return "Отменить написание материала?"

    async def _ask_cancel_writing(
        callback: CallbackQuery,
        state: FSMContext,
        bot: Bot,
        *,
        nav_parent: str | None = None,
    ) -> None:
        if callback.from_user is None:
            return
        data = await state.get_data()
        if nav_parent:
            await state.update_data(nav_parent=nav_parent)
        confirm = await bot.send_message(
            callback.from_user.id,
            await _cancel_prompt_text(state),
            reply_markup=cancel_writing_keyboard(),
        )
        ephemeral = list(data.get("ephemeral_ids", []))
        ephemeral.append(confirm.message_id)
        await state.update_data(
            ephemeral_ids=ephemeral,
            cancel_confirm_id=confirm.message_id,
        )

    def _submit_chooser_markup():
        from aiogram.types import InlineKeyboardButton

        return with_back(
            [
                [InlineKeyboardButton(text="Предложить пост", callback_data="submit:post")],
                [InlineKeyboardButton(text="Предложить мем", callback_data="submit:meme")],
            ],
            "menu:home",
        )

    async def _show_submit_chooser(bot: Bot, telegram_id: int) -> None:
        await bot.send_message(
            telegram_id,
            "Что готовим к публикации?",
            reply_markup=_submit_chooser_markup(),
        )

    async def _show_post_topic_chooser(
        bot: Bot, telegram_id: int, user: User, *, back_to: str
    ) -> None:
        from aiogram.types import InlineKeyboardButton

        prefix = "submit" if back_to == "menu:submit" else "compose"
        rows = [[InlineKeyboardButton(text="Будни", callback_data=f"{prefix}:story")]]
        if _can_propose_important(user):
            rows.append(
                [InlineKeyboardButton(text="Важное", callback_data=f"{prefix}:important")]
            )
        await bot.send_message(
            telegram_id,
            "Для какого топика пост?" if prefix == "submit" else "Куда публикуем?",
            reply_markup=with_back(rows, back_to),
        )

    async def _navigate_after_cancel(
        bot: Bot, telegram_id: int, nav_parent: str
    ) -> None:
        if nav_parent == "menu:staff":
            async with factory.begin() as session:
                user = await session.get(User, telegram_id)
                if user is not None:
                    await upsert_status_card(bot, session, user, markup=staff_menu(user))
            return
        if nav_parent == "menu:submit":
            await _show_submit_chooser(bot, telegram_id)
            return
        if nav_parent in {"submit:post", "staff:new_post"}:
            async with factory() as session:
                user = await current_user(session, telegram_id)
            back_to = "menu:submit" if nav_parent == "submit:post" else "menu:staff"
            await _show_post_topic_chooser(bot, telegram_id, user, back_to=back_to)
            return
        await refresh_home(bot, telegram_id)

    @router.message(CommandStart())
    async def start(message: Message, bot: Bot) -> None:
        if not message.from_user:
            return
        async with factory.begin() as session:
            user = await register_user(
                session,
                message.from_user.id,
                message.from_user.full_name,
                message.from_user.username,
            )
            approved = user.is_approved
            pending = None if approved else await get_pending_application(session, user.telegram_id)
            telegram_id = user.telegram_id
        async with factory.begin() as session:
            user = await session.get(User, telegram_id)
            assert user is not None
            await sync_user_commands(bot, user)
            await delete_quietly(message)
            if approved:
                await bot.send_message(
                    telegram_id,
                    phrase("onboarding", "recognized"),
                    reply_markup=ReplyKeyboardRemove(),
                )
                await upsert_status_card(bot, session, user)
                return
            if pending is not None:
                await bot.send_message(
                    telegram_id,
                    phrase("onboarding", "pending"),
                    reply_markup=ReplyKeyboardRemove(),
                )
                return
            await bot.send_message(
                telegram_id,
                phrase("onboarding", "welcome"),
                reply_markup=ReplyKeyboardRemove(),
            )
            await bot.send_message(
                telegram_id,
                phrase("onboarding", "choose_path"),
                reply_markup=onboarding_keyboard(),
            )

    @router.message(F.text.casefold() == "приклониться")
    @router.message(Command("bow"))
    async def ritual_bow(message: Message, bot: Bot) -> None:
        if not message.from_user:
            return
        async with factory.begin() as session:
            user = await session.get(User, message.from_user.id)
            if user is None or not user.is_approved:
                await start(message, bot)
                return
            if user.staff_role is not None:
                await _send_private(bot, message.from_user.id, phrase("ritual", "denied"))
                return
            try:
                result = await perform_ritual(session, user, tz=settings.tz)
                text = result.message
                streak = result.streak
                uid = user.telegram_id
                ttl = await get_int_setting(
                    session,
                    "ritual_reply_ttl_seconds",
                    int(setting_default("ritual_reply_ttl_seconds")),
                )
                await upsert_status_card(bot, session, user)
            except RitualError as exc:
                if str(exc) == phrase("ritual", "denied"):
                    await _send_private(bot, message.from_user.id, str(exc))
                else:
                    await message.answer(str(exc))
                return
        reply = await message.answer(text)
        if streak > 0 and streak % 7 == 0:
            async with factory.begin() as session:
                await maybe_send_flavor(
                    bot,
                    event_key="ritual_streak_7",
                    user_id=uid,
                    chat_id=message.chat.id,
                    session=session,
                )
        await asyncio.sleep(ttl)
        await delete_quietly(reply)

    @router.callback_query(F.data == "menu:ritual")
    async def menu_ritual(callback: CallbackQuery, bot: Bot) -> None:
        if callback.from_user is None:
            return
        async with factory.begin() as session:
            user = await current_user(session, callback.from_user.id)
            try:
                result = await perform_ritual(session, user, tz=settings.tz)
                text = result.message
                streak = result.streak
                uid = user.telegram_id
                ttl = await get_int_setting(
                    session,
                    "ritual_reply_ttl_seconds",
                    int(setting_default("ritual_reply_ttl_seconds")),
                )
                await upsert_status_card(bot, session, user)
            except RitualError as exc:
                if str(exc) == phrase("ritual", "denied"):
                    await callback.answer()
                    await _send_private(bot, callback.from_user.id, str(exc))
                else:
                    await callback.answer(str(exc), show_alert=True)
                return
        await callback.answer()
        reply = await bot.send_message(callback.from_user.id, text)
        if streak > 0 and streak % 7 == 0:
            async with factory.begin() as session:
                await maybe_send_flavor(
                    bot,
                    event_key="ritual_streak_7",
                    user_id=uid,
                    session=session,
                )
        await asyncio.sleep(ttl)
        await delete_quietly(reply)

    @router.message(Command("card"))
    async def show_card(message: Message, bot: Bot) -> None:
        if not message.from_user:
            return
        parts = (message.text or "").split(maxsplit=1)
        async with factory() as session:
            if len(parts) < 2:
                target = await session.get(User, message.from_user.id)
            else:
                raw = parts[1].strip().lstrip("@")
                if raw.isdigit():
                    target = await session.get(User, int(raw))
                else:
                    target = await session.scalar(
                        select(User).where(func.lower(User.username) == raw.lower())
                    )
            if target is None or not target.is_approved:
                await message.answer("Участник не найден.")
                return
            jobs_done = await count_assignee_done_jobs(session, target.telegram_id)
            posts = await count_user_publications(session, target.telegram_id)
            await send_profile_card(
                bot, message.chat.id, target, jobs_done=jobs_done, posts=posts
            )

    @router.callback_query(F.data == "menu:profile")
    async def menu_profile(callback: CallbackQuery, bot: Bot, state: FSMContext) -> None:
        if callback.from_user is None:
            return
        await state.clear()
        async with factory() as session:
            user = await current_user(session, callback.from_user.id)
            if user.staff_role is not None:
                await callback.answer("Профиль участника доступен только послушникам", show_alert=True)
                return
            jobs_done = await count_assignee_done_jobs(session, user.telegram_id)
            posts = await count_user_publications(session, user.telegram_id)
            open_to_jobs = bool(user.job_notify_enabled)
            await callback.answer()
            if callback.message:
                await delete_quietly(callback.message)
            await send_profile_card(
                bot,
                callback.from_user.id,
                user,
                jobs_done=jobs_done,
                posts=posts,
                reply_markup=profile_menu_keyboard(open_to_jobs=open_to_jobs),
            )

    @router.callback_query(F.data == "profile:edit_bio")
    async def profile_edit_bio(callback: CallbackQuery, bot: Bot, state: FSMContext) -> None:
        if callback.from_user is None:
            return
        async with factory() as session:
            user = await current_user(session, callback.from_user.id)
            if user.staff_role is not None:
                await callback.answer("Недоступно", show_alert=True)
                return
        await state.set_state(ProfileState.bio)
        await callback.answer()
        if callback.message:
            await delete_quietly(callback.message)
        prompt = await bot.send_message(
            callback.from_user.id,
            phrase("profile", "ask_bio"),
            reply_markup=back_keyboard("menu:profile"),
        )
        await state.update_data(ephemeral_ids=[prompt.message_id])

    @router.message(ProfileState.bio)
    async def profile_bio_save(message: Message, bot: Bot, state: FSMContext) -> None:
        if not message.from_user:
            return
        data = await state.get_data()
        ephemeral = list(data.get("ephemeral_ids", []))
        raw = (message.text or "").strip()
        try:
            if raw in {"-", "—", "–"}:
                bio_value: str | None = None
                cleared = True
            else:
                bio_value = normalize_bio(raw)
                if not bio_value:
                    raise ValueError("Пустой текст. Отправь «-», чтобы очистить.")
                cleared = False
        except ValueError as exc:
            warn = await message.answer(str(exc))
            ephemeral.append(warn.message_id)
            await state.update_data(ephemeral_ids=ephemeral)
            await delete_quietly(message)
            return
        async with factory.begin() as session:
            user = await current_user(session, message.from_user.id)
            user.bio = bio_value
            jobs_done = await count_assignee_done_jobs(session, user.telegram_id)
            open_to_jobs = bool(user.job_notify_enabled)
            await upsert_status_card(bot, session, user)
            await state.clear()
            await delete_ids(bot, message.chat.id, *ephemeral)
            await delete_quietly(message)
            notice = await message.answer(
                phrase("profile", "bio_cleared" if cleared else "bio_saved")
            )
            await send_profile_card(
                bot,
                message.from_user.id,
                user,
                jobs_done=jobs_done,
                reply_markup=profile_menu_keyboard(open_to_jobs=open_to_jobs),
            )
        await asyncio.sleep(8)
        await delete_quietly(notice)

    @router.callback_query(F.data == "profile:edit_skills")
    async def profile_edit_skills(callback: CallbackQuery, bot: Bot) -> None:
        if callback.from_user is None:
            return
        async with factory() as session:
            from lab21_bot.services.skill_catalog import reload_skills_cache

            await reload_skills_cache(session)
            user = await current_user(session, callback.from_user.id)
            if user.staff_role is not None:
                await callback.answer("Недоступно", show_alert=True)
                return
            owned = list(user.skill_ids or [])
        await callback.answer()
        if callback.message:
            await delete_quietly(callback.message)
        await bot.send_message(
            callback.from_user.id,
            phrase("profile", "skills_hint"),
            reply_markup=profile_skills_keyboard(owned),
        )

    @router.callback_query(F.data.startswith("profile_skill:"))
    async def profile_skill_toggle(callback: CallbackQuery, bot: Bot) -> None:
        if callback.from_user is None or callback.data is None:
            return
        skill_id = callback.data.split(":", 1)[1]
        try:
            async with factory.begin() as session:
                user = await current_user(session, callback.from_user.id)
                owned = set(user.skill_ids or [])
                title = skill_title(skill_id)
                if skill_id in owned:
                    removed = await remove_member_skill(session, user, skill_id)
                    text = (
                        phrase("profile", "skill_removed", skill=title)
                        if removed
                        else phrase("skills", "already_have")
                    )
                else:
                    mode, _app = await request_member_skill(session, user, skill_id)
                    if mode == "owned":
                        text = phrase("skills", "already_have")
                    elif mode == "validation":
                        text = phrase("skills", "validation_sent", skill=title)
                    else:
                        text = phrase("skills", "added", skill=title)
                owned_list = list(user.skill_ids or [])
                await upsert_status_card(bot, session, user)
            await callback.answer()
            if callback.message:
                try:
                    await callback.message.edit_text(
                        text,
                        reply_markup=profile_skills_keyboard(owned_list),
                    )
                except TelegramBadRequest:
                    await bot.send_message(
                        callback.from_user.id,
                        text,
                        reply_markup=profile_skills_keyboard(owned_list),
                    )
        except (AccessDenied, ApplicationError) as exc:
            await callback.answer(str(exc), show_alert=True)

    @router.callback_query(F.data == "profile:toggle_jobs")
    async def profile_toggle_jobs(callback: CallbackQuery, bot: Bot) -> None:
        if callback.from_user is None:
            return
        async with factory.begin() as session:
            user = await current_user(session, callback.from_user.id)
            if user.staff_role is not None:
                await callback.answer("Недоступно", show_alert=True)
                return
            user.job_notify_enabled = not bool(user.job_notify_enabled)
            enabled = bool(user.job_notify_enabled)
            jobs_done = await count_assignee_done_jobs(session, user.telegram_id)
            await upsert_status_card(bot, session, user)
            await callback.answer(
                phrase("jobs", "notify_on" if enabled else "notify_off"),
                show_alert=True,
            )
            if callback.message:
                await delete_quietly(callback.message)
            await send_profile_card(
                bot,
                callback.from_user.id,
                user,
                jobs_done=jobs_done,
                reply_markup=profile_menu_keyboard(open_to_jobs=enabled),
            )

    @router.message(Command("bless"))
    async def bless_command(message: Message) -> None:
        if not message.from_user:
            return
        parts = (message.text or "").split(maxsplit=1)
        if len(parts) < 2:
            await message.answer(phrase("bless", "usage"))
            return
        raw = parts[1].strip().lstrip("@")
        try:
            async with factory.begin() as session:
                actor = await current_user(session, message.from_user.id)
                if raw.isdigit():
                    target = await session.get(User, int(raw))
                else:
                    target = await session.scalar(
                        select(User).where(func.lower(User.username) == raw.lower())
                    )
                if target is None:
                    raise BlessError("Участник не найден")
                await bless_member(session, actor, target)
                name = target.full_name
            await message.answer(phrase("bless", "ok", name=name))
        except (BlessError, AccessDenied) as exc:
            await message.answer(str(exc))

    @router.callback_query(F.data.in_({"join:community", "join:staff"}))
    async def choose_join_path(callback: CallbackQuery, state: FSMContext, bot: Bot) -> None:
        if callback.from_user is None or callback.data is None:
            return
        kind = JoinKind.STAFF if callback.data.endswith("staff") else JoinKind.COMMUNITY
        try:
            async with factory.begin() as session:
                user = await register_user(
                    session,
                    callback.from_user.id,
                    callback.from_user.full_name,
                    callback.from_user.username,
                )
                if user.is_approved:
                    await sync_user_commands(bot, user)
                    await callback.answer("Вы уже приняты")
                    async with factory.begin() as session:
                        fresh = await session.get(User, user.telegram_id)
                        if fresh is not None:
                            await upsert_status_card(bot, session, fresh)
                    return
                if kind is JoinKind.COMMUNITY:
                    pending = await get_pending_application(session, user.telegram_id)
                    if pending is not None:
                        raise ApplicationError("Заявка уже ожидает решения")
                    telegram_id = user.telegram_id
                else:
                    application = await submit_application(
                        session,
                        user,
                        kind,
                        expire_days=settings.application_expire_days,
                    )
                    application_id = application.id
                    expires_at = application.expires_at
                    full_name = user.full_name
                    username = user.username
                    telegram_id = user.telegram_id
                    kind_label = "сотрудник"
                    notify_body = (
                        f"Тип: {kind_label}\n"
                        f"{full_name}"
                        + (f" (@{username})" if username else "")
                        + f"\nID: {telegram_id}\n"
                        f"Заявка #{application_id}\n"
                        f"Автоотказ: {expires_at:%d.%m.%Y}"
                    )
                    await notify_admin_event(
                        session,
                        settings,
                        "join_staff",
                        title="Новая заявка на вступление",
                        body=notify_body,
                        link="/community",
                        bot=bot,
                    )
        except ApplicationError as exc:
            await callback.answer(str(exc), show_alert=True)
            return

        await callback.answer()
        if isinstance(callback.message, Message):
            await delete_quietly(callback.message)

        if kind is JoinKind.COMMUNITY:
            await state.set_state(JoinState.bio)
            await bot.send_message(telegram_id, phrase("onboarding", "ask_bio"))
            return

        await bot.send_message(telegram_id, phrase("onboarding", "pending"))

    @router.message(JoinState.bio)
    async def join_bio(message: Message, state: FSMContext) -> None:
        if not message.from_user:
            return
        bio = (message.text or "").strip()
        if not bio or bio.startswith("/"):
            await message.answer(phrase("onboarding", "ask_bio"))
            return
        await state.update_data(bio=bio)
        await state.set_state(JoinState.skills)
        await message.answer(phrase("onboarding", "ask_skills"))

    @router.message(JoinState.skills)
    async def join_skills_text(message: Message, state: FSMContext, bot: Bot) -> None:
        if not message.from_user:
            return
        skills_text = (message.text or "").strip()
        if not skills_text or skills_text.startswith("/"):
            await message.answer(phrase("onboarding", "skills_needed"))
            return
        data = await state.get_data()
        bio = str(data.get("bio") or "").strip()
        try:
            async with factory.begin() as session:
                user = await register_user(
                    session,
                    message.from_user.id,
                    message.from_user.full_name,
                    message.from_user.username,
                )
                application = await submit_application(
                    session,
                    user,
                    JoinKind.COMMUNITY,
                    expire_days=settings.application_expire_days,
                    bio=bio,
                    skills_text=skills_text,
                )
                application_id = application.id
                expires_at = application.expires_at
                full_name = user.full_name
                username = user.username
                telegram_id = user.telegram_id
                notify_body = (
                    "Тип: послушник\n"
                    f"{full_name}"
                    + (f" (@{username})" if username else "")
                    + f"\nID: {telegram_id}\n"
                    f"Заявка #{application_id}\n"
                    f"О себе: {bio}\n"
                    f"Навыки (текст): {skills_text}\n"
                    f"Автоотказ: {expires_at:%d.%m.%Y}"
                )
                await notify_admin_event(
                    session,
                    settings,
                    "join_community",
                    title="Новая заявка на вступление",
                    body=notify_body,
                    link="/community",
                    bot=bot,
                )
        except ApplicationError as exc:
            await message.answer(str(exc))
            return
        await state.clear()
        await bot.send_message(telegram_id, phrase("onboarding", "pending"))

    @router.message(Command("menu"))
    async def show_menu(message: Message, bot: Bot) -> None:
        if not message.from_user:
            return
        async with factory.begin() as session:
            user = await current_user(session, message.from_user.id)
            await sync_user_commands(bot, user)
            await delete_quietly(message)
            await upsert_status_card(bot, session, user)

    @router.callback_query(F.data == "menu:home")
    async def menu_home(callback: CallbackQuery, state: FSMContext, bot: Bot) -> None:
        if callback.from_user is None:
            return
        if await _is_writing(state):
            await callback.answer()
            await state.update_data(nav_parent="menu:home")
            await _ask_cancel_writing(callback, state, bot)
            return
        data = await state.get_data()
        ephemeral = list(data.get("ephemeral_ids", []))
        await state.clear()
        await callback.answer()
        if callback.message:
            text = callback.message.text or ""
            chooser = text.startswith(
                (
                    "Что готовим",
                    "Для какого топика",
                    "Куда публикуем",
                    "Инструкция",
                    "Введи артикул",
                    "Выбери: заказ",
                    "Опиши задачу",
                    "Отметь навыки",
                    "Минимум считается",
                )
            )
            if chooser:
                await delete_quietly(callback.message)
            elif ephemeral:
                await delete_ids(bot, callback.message.chat.id, *ephemeral)
        await refresh_home(bot, callback.from_user.id)

    @router.callback_query(F.data == "flow:cancel_ask")
    async def flow_cancel_ask(callback: CallbackQuery, state: FSMContext, bot: Bot) -> None:
        if callback.from_user is None:
            return
        if not await _is_writing(state):
            await callback.answer()
            await state.clear()
            await refresh_home(bot, callback.from_user.id)
            return
        await callback.answer()
        await _ask_cancel_writing(callback, state, bot)

    @router.callback_query(F.data == "flow:cancel_yes")
    async def flow_cancel_yes(callback: CallbackQuery, state: FSMContext, bot: Bot) -> None:
        if callback.from_user is None:
            return
        data = await state.get_data()
        nav_parent = str(data.get("nav_parent") or "menu:home")
        ephemeral = list(data.get("ephemeral_ids", []))
        await state.clear()
        await callback.answer("Отменено")
        if callback.message:
            ephemeral.append(callback.message.message_id)
            await delete_ids(bot, callback.message.chat.id, *ephemeral)
        await _navigate_after_cancel(bot, callback.from_user.id, nav_parent)

    @router.callback_query(F.data == "flow:cancel_no")
    async def flow_cancel_no(callback: CallbackQuery, state: FSMContext, bot: Bot) -> None:
        if callback.from_user is None:
            return
        data = await state.get_data()
        confirm_id = data.get("cancel_confirm_id")
        ephemeral = list(data.get("ephemeral_ids", []))
        if confirm_id in ephemeral:
            ephemeral = [mid for mid in ephemeral if mid != confirm_id]
            await state.update_data(ephemeral_ids=ephemeral, cancel_confirm_id=None)
        await callback.answer("Продолжаем")
        await delete_quietly(callback.message)

    @router.callback_query(F.data == "menu:help")
    async def menu_help(callback: CallbackQuery, bot: Bot) -> None:
        if callback.from_user is None:
            return
        async with factory() as session:
            user = await current_user(session, callback.from_user.id)
            text = build_help_text(user)
        await callback.answer()
        await bot.send_message(
            callback.from_user.id,
            text,
            reply_markup=back_keyboard("menu:home"),
        )

    @router.callback_query(F.data == "menu:skills")
    async def menu_skills(callback: CallbackQuery, bot: Bot) -> None:
        if callback.from_user is None:
            return
        await callback.answer()
        await bot.send_message(
            callback.from_user.id,
            "Выбери навык:",
            reply_markup=skill_board_keyboard(),
        )

    @router.callback_query(F.data == "menu:add_skill")
    async def menu_add_skill(callback: CallbackQuery, bot: Bot) -> None:
        if callback.from_user is None:
            return
        async with factory() as session:
            from lab21_bot.services.skill_catalog import reload_skills_cache

            await reload_skills_cache(session)
            user = await current_user(session, callback.from_user.id)
            if user.staff_role is not None:
                await callback.answer("Сотрудникам навыки не назначаются", show_alert=True)
                return
            owned = list(user.skill_ids or [])
        await callback.answer()
        await bot.send_message(
            callback.from_user.id,
            phrase("skills", "add_prompt"),
            reply_markup=add_skill_keyboard(owned),
        )

    @router.callback_query(F.data.startswith("add_skill:"))
    async def add_skill_pick(callback: CallbackQuery, bot: Bot) -> None:
        if callback.from_user is None or callback.data is None:
            return
        skill_id = callback.data.split(":", 1)[1]
        try:
            async with factory.begin() as session:
                user = await current_user(session, callback.from_user.id)
                mode, _app = await request_member_skill(session, user, skill_id)
                title = skill_title(skill_id)
                owned = list(user.skill_ids or [])
            if mode == "owned":
                text = phrase("skills", "already_have")
            elif mode == "validation":
                text = phrase("skills", "validation_sent", skill=title)
            else:
                text = phrase("skills", "added", skill=title)
            await callback.answer()
            await bot.send_message(
                callback.from_user.id,
                text,
                reply_markup=add_skill_keyboard(owned),
            )
        except (AccessDenied, ApplicationError) as exc:
            await callback.answer(str(exc), show_alert=True)

    @router.callback_query(F.data.startswith("skills_board:"))
    async def skills_board_pick(callback: CallbackQuery, bot: Bot) -> None:
        if callback.from_user is None or callback.data is None:
            return
        skill_id = callback.data.split(":", 1)[1]
        async with factory() as session:
            await current_user(session, callback.from_user.id)
            members = await members_with_skill(session, skill_id)
            text = format_skill_board(skill_id, members)
        await callback.answer()
        await bot.send_message(
            callback.from_user.id,
            text,
            reply_markup=back_keyboard("menu:skills"),
        )

    @router.callback_query(F.data == "menu:my_quests")
    async def menu_my_quests(callback: CallbackQuery, bot: Bot) -> None:
        if callback.from_user is None:
            return
        async with factory() as session:
            await current_user(session, callback.from_user.id)
            quests = await user_open_quest_memberships(session, callback.from_user.id)
        await callback.answer()
        if not quests:
            await bot.send_message(
                callback.from_user.id,
                phrase("quests", "none_open"),
                reply_markup=back_keyboard("menu:home"),
            )
            return
        lines = [f"#{q.number} — {q.title}" for q in quests]
        await bot.send_message(
            callback.from_user.id,
            "Твои квесты:\n" + "\n".join(lines),
            reply_markup=my_quests_keyboard(quests),
        )

    @router.callback_query(F.data == "menu:my_jobs")
    async def menu_my_jobs(callback: CallbackQuery, state: FSMContext, bot: Bot) -> None:
        if callback.from_user is None:
            return
        await state.clear()
        async with factory() as session:
            await current_user(session, callback.from_user.id)
            jobs = await list_assignee_claimed_jobs(session, callback.from_user.id)
        await callback.answer()
        if callback.message:
            await delete_quietly(callback.message)
        if not jobs:
            await bot.send_message(
                callback.from_user.id,
                phrase("jobs", "my_jobs_empty"),
                reply_markup=back_keyboard("menu:home"),
            )
            return
        await bot.send_message(
            callback.from_user.id,
            phrase("jobs", "my_jobs_hint"),
            reply_markup=my_jobs_keyboard(jobs),
        )

    @router.callback_query(F.data.startswith("job_board:"))
    async def job_board_status_tap(callback: CallbackQuery) -> None:
        if callback.data is None:
            return
        kind = callback.data.split(":")[1] if ":" in callback.data else ""
        if kind == "busy":
            await callback.answer("Заказ уже в работе", show_alert=True)
        elif kind == "done":
            await callback.answer("Заказ уже выполнен", show_alert=True)
        else:
            await callback.answer("Заказ отменён", show_alert=True)

    @router.callback_query(F.data.startswith("job_claim:"))
    async def job_claim_button(callback: CallbackQuery, bot: Bot) -> None:
        if callback.from_user is None or callback.data is None:
            return
        job_id = int(callback.data.split(":", 1)[1])
        job_dest = job_destination(settings)
        fallback_thread = job_dest.thread_id if job_dest is not None else None
        async with factory.begin() as session:
            claimant = await session.get(User, callback.from_user.id)
            if claimant is None or not claimant.is_approved or not claimant.is_active:
                await callback.answer("Сначала напиши боту /start", show_alert=True)
                return
            try:
                claimed = await claim_service_job(session, job_id, claimant)
            except JobError as exc:
                reason = str(exc)
                job = await get_job(session, job_id)
                if reason == "missing_skill":
                    have = set(claimant.skill_ids or [])
                    missing = [
                        skill_title(sid)
                        for sid in list(job.skill_ids or [])
                        if sid not in have
                    ] if job is not None else []
                    deny_text = phrase(
                        "jobs",
                        "claim_deny",
                        skill=", ".join(missing) or "—",
                    )
                elif reason == "own_job":
                    deny_text = phrase("jobs", "claim_own")
                else:
                    deny_text = phrase("jobs", "claim_taken")
                    if job is not None:
                        await sync_job_board_post(bot, job)
                await callback.answer(deny_text, show_alert=True)
                return
            handle = (
                f"@{claimant.username}" if claimant.username else claimant.full_name
            )
            note = (claimed.assignee_note or "").strip()
            await sync_job_board_post(bot, claimed)
        await callback.answer("Заказ взят в работу")
        board = callback.message if isinstance(callback.message, Message) else None
        announced = False
        if board is not None:
            thread_id = board.message_thread_id
            if thread_id is None:
                thread_id = fallback_thread
            thread_kwargs: dict[str, Any] = {}
            if thread_id is not None:
                thread_kwargs["message_thread_id"] = thread_id
            try:
                await bot.send_message(
                    board.chat.id,
                    f"Заказ взял в работу {handle}",
                    reply_to_message_id=board.message_id,
                    **thread_kwargs,
                )
                announced = True
            except (TelegramBadRequest, TelegramForbiddenError):
                try:
                    await bot.send_message(
                        board.chat.id,
                        f"Заказ взял в работу {handle}",
                        **thread_kwargs,
                    )
                    announced = True
                except (TelegramBadRequest, TelegramForbiddenError):
                    announced = False
        if not announced:
            _log.warning("job_claim_announce_failed", job_id=job_id)
        try:
            await bot.send_message(
                callback.from_user.id,
                phrase("jobs", "claim_ok", job_id=job_id),
            )
            if note:
                await bot.send_message(
                    callback.from_user.id,
                    phrase("jobs", "claim_note", note=note),
                )
        except (TelegramBadRequest, TelegramForbiddenError):
            _log.info("job_claim_dm_failed", job_id=job_id, user_id=callback.from_user.id)

    @router.callback_query(F.data.startswith("job_done:"))
    async def job_done_pick(callback: CallbackQuery, state: FSMContext, bot: Bot) -> None:
        if callback.from_user is None or callback.data is None:
            return
        job_id = int(callback.data.split(":", 1)[1])
        async with factory() as session:
            await current_user(session, callback.from_user.id)
            job = await get_job(session, job_id)
            if (
                job is None
                or job.assignee_id != callback.from_user.id
                or job.status is not ServiceJobStatus.CLAIMED
            ):
                await callback.answer(phrase("jobs", "my_jobs_empty"), show_alert=True)
                return
        await state.set_state(JobResultState.report)
        await state.update_data(job_result_id=job_id, job_result_media=[])
        await callback.answer()
        if callback.message:
            await delete_quietly(callback.message)
        prompt = await bot.send_message(
            callback.from_user.id,
            phrase("jobs", "ask_result", job_id=job_id),
            reply_markup=back_keyboard("menu:my_jobs"),
        )
        await state.update_data(ephemeral_ids=[prompt.message_id])

    @router.message(JobResultState.report)
    async def job_result_report(message: Message, state: FSMContext, bot: Bot) -> None:
        if not message.from_user:
            return
        batch = await albums.collect(message)
        if batch is None:
            return
        data = await state.get_data()
        job_id = int(data.get("job_result_id") or 0)
        ephemeral = list(data.get("ephemeral_ids", []))
        text = (
            next(
                (item.caption or item.text for item in batch if item.caption or item.text),
                "",
            )
            or ""
        ).strip()
        media = _media_from_messages(batch)
        if not text and not media:
            await message.answer(phrase("jobs", "result_needed"))
            return
        try:
            async with factory.begin() as session:
                user = await current_user(session, message.from_user.id)
                job = await submit_job_result(
                    session,
                    user,
                    job_id,
                    result_text=text,
                    result_media=media,
                )
                customer_id = job.customer_id
                description = job.description
                report = (job.result_text or "").strip() or "(фото)"
                result_media = list(job.result_media or [])
                job_pk = job.id
        except (JobError, AccessDenied) as exc:
            await message.answer(str(exc))
            return
        await state.clear()
        await delete_ids(bot, message.chat.id, *ephemeral)
        for item in batch:
            await delete_quietly(item)
        await message.answer(phrase("jobs", "result_sent", job_id=job_pk))
        customer_text = phrase(
            "jobs",
            "result_for_customer",
            job_id=job_pk,
            description=description,
            report=report,
        )
        markup = job_result_review_keyboard(job_pk)
        try:
            if result_media:
                first = result_media[0]
                if first.get("type") == "photo" and first.get("file_id"):
                    await bot.send_photo(
                        customer_id,
                        first["file_id"],
                        caption=customer_text[:1024],
                        reply_markup=markup,
                    )
                    for extra in result_media[1:]:
                        if extra.get("type") == "photo" and extra.get("file_id"):
                            await bot.send_photo(customer_id, extra["file_id"])
                else:
                    await bot.send_message(customer_id, customer_text, reply_markup=markup)
            else:
                await bot.send_message(customer_id, customer_text, reply_markup=markup)
        except (TelegramBadRequest, TelegramForbiddenError):
            pass
        await refresh_home(bot, message.from_user.id)

    @router.callback_query(F.data.regexp(r"^job_review:(ok|no):\d+$"))
    async def job_review_decide(callback: CallbackQuery, bot: Bot) -> None:
        if callback.from_user is None or callback.data is None:
            return
        _, decision, raw_id = callback.data.split(":", 2)
        job_id = int(raw_id)
        try:
            async with factory.begin() as session:
                customer = await current_user(session, callback.from_user.id)
                if decision == "no":
                    job = await reject_job_result(session, customer, job_id)
                    assignee_id = job.assignee_id
                    await callback.answer()
                    if isinstance(callback.message, Message):
                        try:
                            await callback.message.edit_reply_markup(reply_markup=None)
                        except TelegramBadRequest:
                            pass
                    await bot.send_message(
                        callback.from_user.id,
                        phrase("jobs", "result_rejected_customer", job_id=job.id),
                    )
                    if assignee_id:
                        try:
                            await bot.send_message(
                                assignee_id,
                                phrase("jobs", "result_rejected_assignee"),
                            )
                        except (TelegramBadRequest, TelegramForbiddenError):
                            pass
                    return

                job, item = await confirm_job_result(
                    session,
                    customer,
                    job_id,
                    job_thread_id=settings.job_thread_id,
                )
                assignee_id = job.assignee_id
                respect = job.respect_reward
                content_id = item.id
                await callback.answer()
                if isinstance(callback.message, Message):
                    try:
                        await callback.message.edit_reply_markup(reply_markup=None)
                    except TelegramBadRequest:
                        pass
                from lab21_bot.services.job_publish import mark_job_board_done

                await mark_job_board_done(bot, job, customer)
                await bot.send_message(
                    callback.from_user.id,
                    phrase("jobs", "result_confirmed_customer", job_id=job.id),
                )
                if assignee_id:
                    try:
                        await bot.send_message(
                            assignee_id,
                            phrase(
                                "jobs",
                                "result_confirmed_assignee",
                                job_id=job.id,
                                respect=respect,
                            ),
                        )
                    except (TelegramBadRequest, TelegramForbiddenError):
                        pass
                # Notify content moderators via existing staff flow if any are online — optional.
                _ = content_id
        except (JobError, AccessDenied) as exc:
            await callback.answer(str(exc), show_alert=True)

    @router.callback_query(F.data.startswith("quest_join:"))
    async def quest_join_cb(callback: CallbackQuery, bot: Bot) -> None:
        if callback.from_user is None or callback.data is None:
            return
        quest_id = int(callback.data.split(":", 1)[1])
        try:
            async with factory.begin() as session:
                from lab21_bot.services.quests import get_quest

                user = await current_user(session, callback.from_user.id)
                quest = await get_quest(session, quest_id)
                await join_quest(session, quest, user)
                quest = await get_quest(session, quest_id)
                members = await quest_member_users(quest)
                html = format_quest_html(quest, members)
                if quest.chat_id and quest.message_id:
                    try:
                        await edit_quest_post_html(
                            bot, quest, html, joined=True
                        )
                    except (TelegramBadRequest, TelegramForbiddenError):
                        pass
            await callback.answer(phrase("quests", "joined"), show_alert=True)
        except (QuestError, AccessDenied) as exc:
            text = str(exc)
            if text == phrase("quests", "already_joined"):
                try:
                    async with factory.begin() as session:
                        from lab21_bot.services.quests import get_quest

                        quest = await get_quest(session, quest_id)
                        members = await quest_member_users(quest)
                        html = format_quest_html(quest, members)
                        if quest.chat_id and quest.message_id:
                            await edit_quest_post_html(
                                bot, quest, html, joined=True
                            )
                except (QuestError, TelegramBadRequest, TelegramForbiddenError):
                    pass
            await callback.answer(text, show_alert=True)

    @router.callback_query(F.data.startswith("quest_leave:"))
    async def quest_leave_cb(callback: CallbackQuery, bot: Bot) -> None:
        if callback.from_user is None or callback.data is None:
            return
        quest_id = int(callback.data.split(":", 1)[1])
        try:
            async with factory.begin() as session:
                from lab21_bot.services.quests import get_quest

                await leave_quest(session, quest_id, callback.from_user.id)
                quest = await get_quest(session, quest_id)
                members = await quest_member_users(quest)
                html = format_quest_html(quest, members)
                if quest.chat_id and quest.message_id:
                    try:
                        await edit_quest_post_html(
                            bot, quest, html, joined=False
                        )
                    except (TelegramBadRequest, TelegramForbiddenError):
                        pass
            await callback.answer(phrase("quests", "left"))
        except QuestError as exc:
            text = str(exc)
            if text == phrase("quests", "not_joined"):
                try:
                    async with factory.begin() as session:
                        from lab21_bot.services.quests import get_quest

                        quest = await get_quest(session, quest_id)
                        members = await quest_member_users(quest)
                        html = format_quest_html(quest, members)
                        if quest.chat_id and quest.message_id:
                            await edit_quest_post_html(
                                bot, quest, html, joined=False
                            )
                except (QuestError, TelegramBadRequest, TelegramForbiddenError):
                    pass
            await callback.answer(text, show_alert=True)

    @router.callback_query(F.data == "menu:balance")
    @router.message(Command("balance"))
    async def show_balance(event: Message | CallbackQuery, bot: Bot) -> None:
        telegram_user = event.from_user
        if telegram_user is None:
            return
        async with factory.begin() as session:
            user = await current_user(session, telegram_user.id)
            posts = await count_user_publications(session, user.telegram_id)
            text = status_text(user, posts=posts)
            if isinstance(event, CallbackQuery):
                await event.answer(text, show_alert=True)
                await upsert_status_card(bot, session, user)
            else:
                await delete_quietly(event)
                await upsert_status_card(bot, session, user)

    @router.message(Command("history"))
    async def show_history(message: Message, bot: Bot) -> None:
        if not message.from_user:
            return
        async with factory() as session:
            await current_user(session, message.from_user.id)
            entries = await history(session, message.from_user.id)
            lines = [
                f"{entry.created_at:%d.%m} {entry.delta:+d} — {entry.reason}" for entry in entries
            ]
        reply = await message.answer("\n".join(lines) if lines else "История пока пуста.")
        await delete_quietly(message)
        await asyncio.sleep(20)
        await delete_quietly(reply)
        await refresh_home(bot, message.from_user.id)

    @router.callback_query(F.data.in_({"menu:order", "order:service"}))
    @router.message(Command("order"))
    async def start_order(event: Message | CallbackQuery, state: FSMContext, bot: Bot) -> None:
        if event.from_user is None:
            return
        async with factory() as session:
            await current_user(session, event.from_user.id)
        try:
            prompt = await bot.send_message(
                event.from_user.id,
                phrase("jobs", "ask_description"),
                reply_markup=back_keyboard("order:cancel_draft"),
            )
        except (TelegramBadRequest, TelegramForbiddenError):
            if isinstance(event, CallbackQuery):
                await event.answer(
                    "Напиши боту /start в личных сообщениях, затем нажми снова",
                    show_alert=True,
                )
            else:
                await event.answer("Напиши боту /start в личных сообщениях")
            return
        await state.set_state(ServiceJobState.description)
        if isinstance(event, CallbackQuery):
            await event.answer()
            if event.data == "order:service" and event.message:
                await delete_quietly(event.message)
        else:
            await delete_quietly(event)
        await state.update_data(ephemeral_ids=[prompt.message_id], job_media=[])

    @router.callback_query(F.data == "order:article")
    async def order_article_removed(callback: CallbackQuery) -> None:
        await callback.answer("Товары заказываются в топике Магазин", show_alert=True)

    @router.message(ServiceJobState.description)
    async def service_job_description(message: Message, state: FSMContext, bot: Bot) -> None:
        if not message.from_user:
            return
        data = await state.get_data()
        ephemeral = list(data.get("ephemeral_ids", []))
        text = (message.text or message.caption or "").strip()
        media: list[dict] = []
        if message.photo:
            media = [{"type": "photo", "file_id": message.photo[-1].file_id}]
        if not text and not media:
            await message.answer(phrase("jobs", "ask_description"))
            return
        if not text:
            text = "(фото)"
        await delete_ids(bot, message.chat.id, *ephemeral)
        await delete_quietly(message)
        await state.set_state(ServiceJobState.skill)
        await state.update_data(job_description=text, job_media=media, job_skill_ids=[])
        prompt = await message.answer(
            phrase("jobs", "ask_skill"),
            reply_markup=skill_toggle_keyboard(
                [],
                prefix="job_skill",
                done_data="job_skill:done",
                back_data="order:cancel_draft",
                multi=True,
                show_prices=True,
            ),
        )
        await state.update_data(ephemeral_ids=[prompt.message_id])

    @router.callback_query(ServiceJobState.skill, F.data.startswith("job_skill:"))
    async def service_job_skill(callback: CallbackQuery, state: FSMContext, bot: Bot) -> None:
        if callback.from_user is None or callback.data is None:
            return
        action = callback.data.split(":", 1)[1]
        data = await state.get_data()
        selected = list(data.get("job_skill_ids", []))
        if action == "done":
            if not selected:
                await callback.answer(phrase("jobs", "skills_needed"), show_alert=True)
                return
            floor = min_job_price(selected)
            respect = default_job_respect(selected)
            async with factory() as session:
                user = await current_user(session, callback.from_user.id)
                balance = user.balance
            await state.update_data(job_skill_ids=selected)
            await state.set_state(ServiceJobState.price)
            await callback.answer()
            if callback.message:
                await delete_quietly(callback.message)
            prompt = await bot.send_message(
                callback.from_user.id,
                phrase(
                    "jobs",
                    "ask_price",
                    breakdown=format_skills_price_lines(selected),
                    min_price=floor,
                    respect=respect,
                    balance=balance,
                ),
                reply_markup=back_keyboard("order:cancel_draft"),
            )
            await state.update_data(ephemeral_ids=[prompt.message_id])
            return
        if action == "noop":
            await callback.answer()
            return
        if action in selected:
            selected.remove(action)
        else:
            selected.append(action)
        await state.update_data(job_skill_ids=selected)
        await callback.answer()
        markup = skill_toggle_keyboard(
            selected,
            prefix="job_skill",
            done_data="job_skill:done",
            back_data="order:cancel_draft",
            multi=True,
            show_prices=True,
        )
        if isinstance(callback.message, Message):
            progress = (
                phrase(
                    "jobs",
                    "ask_skill_progress",
                    breakdown=format_skills_price_lines(selected),
                    min_price=min_job_price(selected),
                    respect=default_job_respect(selected),
                )
                if selected
                else phrase("jobs", "ask_skill")
            )
            try:
                await callback.message.edit_text(progress, reply_markup=markup)
            except TelegramBadRequest:
                await callback.message.edit_reply_markup(reply_markup=markup)

    @router.message(ServiceJobState.price)
    async def service_job_price(message: Message, state: FSMContext, bot: Bot) -> None:
        if not message.from_user:
            return
        raw = (message.text or "").strip()
        data = await state.get_data()
        selected = list(data.get("job_skill_ids") or [])
        ephemeral = list(data.get("ephemeral_ids", []))
        floor = min_job_price(selected)
        respect = default_job_respect(selected)
        breakdown = format_skills_price_lines(selected)

        async def _reask(balance: int) -> None:
            await message.answer(
                phrase(
                    "jobs",
                    "ask_price",
                    breakdown=breakdown,
                    min_price=floor,
                    respect=respect,
                    balance=balance,
                )
            )

        try:
            price = int(raw)
        except ValueError:
            async with factory() as session:
                user = await current_user(session, message.from_user.id)
                await _reask(user.balance)
            return
        if price < floor:
            async with factory() as session:
                user = await current_user(session, message.from_user.id)
                await _reask(user.balance)
            return
        await delete_ids(bot, message.chat.id, *ephemeral)
        await delete_quietly(message)
        await state.update_data(job_price=price)
        await state.set_state(ServiceJobState.assignee_note)
        prompt = await message.answer(
            phrase("jobs", "ask_assignee_note"),
            reply_markup=back_keyboard("order:cancel_draft"),
        )
        await state.update_data(ephemeral_ids=[prompt.message_id])

    @router.message(ServiceJobState.assignee_note)
    async def service_job_assignee_note(message: Message, state: FSMContext, bot: Bot) -> None:
        if not message.from_user:
            return
        data = await state.get_data()
        selected = list(data.get("job_skill_ids") or [])
        description = str(data.get("job_description") or "").strip()
        media = list(data.get("job_media") or [])
        ephemeral = list(data.get("ephemeral_ids", []))
        price = int(data.get("job_price") or 0)
        raw_note = (message.text or message.caption or "").strip()
        note = "" if raw_note in {"", "-", "—", "<->"} else raw_note
        try:
            async with factory.begin() as session:
                user = await current_user(session, message.from_user.id)
                job = await create_service_job(
                    session,
                    customer_id=user.telegram_id,
                    skill_ids=selected,
                    description=description,
                    price=price,
                    media=media,
                    assignee_note=note,
                    reserve_funds=True,
                )
                job_id = job.id
                job_price = job.price
                balance_after = user.balance
                await publish_service_job(bot, session, settings, job, user)
                await notify_job_subscribers(bot, session, job)
                await upsert_status_card(bot, session, user)
        except (JobError, AccessDenied) as exc:
            await message.answer(str(exc))
            return
        await state.clear()
        await delete_ids(bot, message.chat.id, *ephemeral)
        await delete_quietly(message)
        await message.answer(
            phrase(
                "jobs",
                "created",
                job_id=job_id,
                price=job_price,
                balance_after=balance_after,
            )
        )
        await refresh_home(bot, message.from_user.id)

    @router.callback_query(F.data == "menu:job_notify")
    async def menu_job_notify(callback: CallbackQuery, bot: Bot) -> None:
        if callback.from_user is None:
            return
        async with factory() as session:
            user = await current_user(session, callback.from_user.id)
            enabled = bool(user.job_notify_enabled)
        await callback.answer()
        text = (
            phrase("jobs", "notify_status_on")
            if enabled
            else phrase("jobs", "notify_status_off")
        )
        if callback.message:
            await delete_quietly(callback.message)
        await bot.send_message(
            callback.from_user.id,
            text,
            reply_markup=job_notify_keyboard(enabled=enabled),
        )

    @router.callback_query(F.data == "jobs:notify_toggle")
    async def toggle_job_notify(callback: CallbackQuery, bot: Bot) -> None:
        if callback.from_user is None:
            return
        async with factory.begin() as session:
            user = await current_user(session, callback.from_user.id)
            user.job_notify_enabled = not bool(user.job_notify_enabled)
            enabled = user.job_notify_enabled
            await session.flush()
        await callback.answer(
            phrase("jobs", "notify_on") if enabled else phrase("jobs", "notify_off")
        )
        text = (
            phrase("jobs", "notify_status_on")
            if enabled
            else phrase("jobs", "notify_status_off")
        )
        if isinstance(callback.message, Message):
            await callback.message.edit_text(
                text,
                reply_markup=job_notify_keyboard(enabled=enabled),
            )

    @router.callback_query(F.data == "order:cancel_draft")
    async def cancel_order_draft(callback: CallbackQuery, state: FSMContext, bot: Bot) -> None:
        data = await state.get_data()
        ephemeral = list(data.get("ephemeral_ids", []))
        await state.clear()
        await callback.answer("Отменено")
        if callback.message:
            ephemeral.append(callback.message.message_id)
            await delete_ids(bot, callback.message.chat.id, *ephemeral)
        if callback.from_user:
            await refresh_home(bot, callback.from_user.id)

    @router.callback_query(F.data.startswith("buy:"))
    async def buy_product_legacy(callback: CallbackQuery) -> None:
        await callback.answer("Заказывай в топике Магазин", show_alert=True)

    @router.callback_query(F.data.startswith("shop_buy:"))
    async def shop_buy_from_board(callback: CallbackQuery, bot: Bot) -> None:
        if callback.from_user is None or callback.data is None:
            return
        if not isinstance(callback.message, Message):
            await callback.answer("Нажми «Заказать» ещё раз в чате Магазин", show_alert=True)
            return
        product_id = int(callback.data.split(":")[-1])
        try:
            async with factory() as session:
                user = await current_user(session, callback.from_user.id)
                product = await session.get(Product, product_id)
                if product is None or not product_is_available(product):
                    await callback.answer("Сейчас этот лот недоступен", show_alert=True)
                    return
                if user.staff_role is not None:
                    await callback.answer("Магазин только для участников", show_alert=True)
                    return
                mention_name = callback.from_user.full_name or user.full_name
                product_name = product.name
            mention = html_user_mention(callback.from_user.id, mention_name)
            try:
                await bot.send_message(
                    callback.message.chat.id,
                    f"{mention}\nКакое количество «{escape(product_name)}» заказать?",
                    parse_mode="HTML",
                    reply_to_message_id=callback.message.message_id,
                    reply_markup=shop_qty_keyboard(
                        product_id, 1, callback.from_user.id
                    ),
                    **_thread_kwargs(callback.message),
                )
            except (TelegramBadRequest, TelegramForbiddenError):
                await callback.answer("Не удалось открыть заказ в этом чате", show_alert=True)
                return
            await callback.answer()
        except AccessDenied as error:
            await callback.answer(telegram_alert_text(str(error)), show_alert=True)

    @router.callback_query(F.data.startswith("shop_qty:"))
    async def shop_qty_step(callback: CallbackQuery) -> None:
        if callback.from_user is None or callback.data is None:
            return
        parts = callback.data.split(":")
        if len(parts) != 5:
            await callback.answer("Некорректная кнопка", show_alert=True)
            return
        _, action, product_raw, qty_raw, buyer_raw = parts
        try:
            product_id = int(product_raw)
            qty = max(1, int(qty_raw))
            buyer_id = int(buyer_raw)
        except ValueError:
            await callback.answer("Некорректная кнопка", show_alert=True)
            return
        if callback.from_user.id != buyer_id:
            await callback.answer("Это заказ другого участника", show_alert=True)
            return
        if action == "nop":
            await callback.answer(f"Количество: {qty}")
            return
        try:
            async with factory() as session:
                user = await current_user(session, callback.from_user.id)
                product = await session.get(Product, product_id)
                if product is None or not product_is_available(product):
                    await callback.answer("Сейчас этот лот недоступен", show_alert=True)
                    return
                already = await count_user_product_qty(
                    session, user.telegram_id, product.id
                )
                ceiling = 99
                if product.stock is not None:
                    ceiling = min(ceiling, max(1, int(product.stock)))
                if product.max_per_user is not None:
                    ceiling = min(ceiling, max(1, int(product.max_per_user) - already))
                if action == "inc":
                    nxt = min(qty + 1, ceiling)
                    if nxt == qty:
                        await callback.answer(f"Максимум {ceiling} шт.")
                        return
                    qty = nxt
                elif action == "dec":
                    nxt = max(1, qty - 1)
                    if nxt == qty:
                        await callback.answer("Минимум 1 шт.")
                        return
                    qty = nxt
                elif action == "ok":
                    preview = shop_order_preview(
                        quantity=qty,
                        unit_price=product.price,
                        balance=user.balance,
                        max_per_user=product.max_per_user,
                        already_qty=already,
                        stock=product.stock,
                    )
                    if not preview.can_confirm:
                        await callback.answer(
                            telegram_alert_text(preview.text), show_alert=True
                        )
                        return
                    mention = html_user_mention(
                        callback.from_user.id,
                        callback.from_user.full_name or user.full_name,
                    )
                    if isinstance(callback.message, Message):
                        try:
                            await callback.message.edit_text(
                                f"{mention}\n{preview.text}",
                                parse_mode="HTML",
                                reply_markup=shop_confirm_keyboard(
                                    product_id, qty, callback.from_user.id
                                ),
                            )
                        except (TelegramBadRequest, TelegramForbiddenError):
                            await callback.answer(
                                telegram_alert_text(preview.text), show_alert=True
                            )
                            return
                    await callback.answer()
                    return
                else:
                    await callback.answer("Некорректная кнопка", show_alert=True)
                    return
            if isinstance(callback.message, Message):
                try:
                    await callback.message.edit_reply_markup(
                        reply_markup=shop_qty_keyboard(
                            product_id, qty, callback.from_user.id
                        )
                    )
                except (TelegramBadRequest, TelegramForbiddenError):
                    pass
            await callback.answer()
        except AccessDenied as error:
            await callback.answer(telegram_alert_text(str(error)), show_alert=True)

    @router.callback_query(F.data.startswith("shop_ok:"))
    async def shop_confirm_buy(callback: CallbackQuery, bot: Bot) -> None:
        if callback.from_user is None or callback.data is None:
            return
        parts = callback.data.split(":")
        if len(parts) != 4:
            await callback.answer("Некорректная кнопка", show_alert=True)
            return
        product_id = int(parts[1])
        quantity = int(parts[2])
        buyer_id = int(parts[3])
        if callback.from_user.id != buyer_id:
            await callback.answer("Это заказ другого участника", show_alert=True)
            return
        try:
            async with factory.begin() as session:
                await current_user(session, callback.from_user.id)
                order = await purchase(
                    session,
                    callback.from_user.id,
                    product_id,
                    quantity=quantity,
                    idempotency_key=f"callback:{callback.id}",
                )
                product = await session.get(Product, product_id)
                assert product is not None
                buyer = await session.get(User, callback.from_user.id)
                assert buyer is not None
                article = product.article
                product_name = product.name
                product_kind = product.kind
                buyer_name = buyer.full_name
                order_id = order.id
                order_qty = order.quantity
                order_actions_markup = order_actions(order)
                service_job = (
                    await get_job_by_order_id(session, order.id)
                    if product.kind is ProductKind.SERVICE
                    else None
                )
                if service_job is not None:
                    await publish_service_job(bot, session, settings, service_job, buyer)
                    await notify_job_subscribers(bot, session, service_job)
                await upsert_status_card(bot, session, buyer)
                await sync_shop_card(bot, product, settings, upload_dir=settings.upload_dir)
                shop_body = (
                    f"[{article}] {product_name} × {order_qty}\n"
                    f"Покупатель: {buyer_name} ({buyer_id})"
                    + (
                        "\nУслуга опубликована в топике заказов."
                        if product_kind is ProductKind.SERVICE
                        else ""
                    )
                )
                await notify_admin_event(
                    session,
                    settings,
                    "shop_order",
                    title=f"Новый заказ #{order_id}",
                    body=shop_body,
                    link="/shop",
                    bot=bot,
                    reply_markup=order_actions_markup,
                )
            await callback.answer("Заказ создан")
            mention = html_user_mention(
                callback.from_user.id,
                callback.from_user.full_name or buyer_name,
            )
            if isinstance(callback.message, Message):
                try:
                    await callback.message.edit_text(
                        f"{mention}\nЗаказ #{order_id} оформлен.",
                        parse_mode="HTML",
                        reply_markup=None,
                    )
                except (TelegramBadRequest, TelegramForbiddenError):
                    pass
        except (EconomyError, AccessDenied) as error:
            await callback.answer(telegram_alert_text(str(error)), show_alert=True)

    @router.callback_query(F.data.startswith("shop_abort:"))
    async def shop_abort_buy(callback: CallbackQuery) -> None:
        if callback.from_user is None or callback.data is None:
            return
        buyer_id = int(callback.data.split(":")[-1])
        if callback.from_user.id != buyer_id:
            await callback.answer("Это заказ другого участника", show_alert=True)
            return
        await callback.answer("Отменено")
        await delete_quietly(callback.message)

    @router.callback_query(F.data.startswith("shop_soldout:"))
    async def shop_soldout(callback: CallbackQuery) -> None:
        await callback.answer("Этот лот сейчас недоступен", show_alert=True)

    @router.message(Command("transfer"))
    async def transfer_command(message: Message) -> None:
        if not message.from_user:
            return
        parts = (message.text or "").split(maxsplit=3)
        if len(parts) < 4:
            await message.answer("Формат: /transfer TELEGRAM_ID СУММА ПРИЧИНА")
            return
        try:
            recipient_id, amount = int(parts[1]), int(parts[2])
            async with factory.begin() as session:
                daily_limit = await get_int_setting(
                    session,
                    "transfer_daily_limit",
                    settings.transfer_daily_limit,
                )
                await transfer(
                    session,
                    message.from_user.id,
                    recipient_id,
                    amount,
                    parts[3],
                    daily_limit,
                    idempotency_key=f"message:{message.chat.id}:{message.message_id}",
                )
            await message.answer(f"Передано {amount} 🙏.")
        except (ValueError, EconomyError) as error:
            await message.answer(str(error))

    @router.message(Command("grant", "withdraw"))
    async def balance_admin(message: Message) -> None:
        if not message.from_user:
            return
        parts = (message.text or "").split(maxsplit=3)
        if len(parts) < 4:
            await message.answer("Формат: /grant TELEGRAM_ID СУММА ПРИЧИНА")
            return
        try:
            target_id, amount = int(parts[1]), int(parts[2])
            grant = parts[0].split("@")[0] == "/grant"
            async with factory.begin() as session:
                actor = await current_user(session, message.from_user.id)
                entry = await change_balance(
                    session,
                    actor,
                    target_id,
                    amount,
                    parts[3],
                    grant=grant,
                    idempotency_key=f"message:{message.chat.id}:{message.message_id}",
                )
            await message.answer(
                f"🙏: {entry.delta:+d}. Итого: {entry.balance_after}."
            )
        except (ValueError, EconomyError, AccessDenied) as error:
            await message.answer(str(error))

    @router.message(Command("respect_grant", "respect_withdraw"))
    async def respect_admin(message: Message) -> None:
        if not message.from_user:
            return
        parts = (message.text or "").split(maxsplit=3)
        if len(parts) < 4:
            await message.answer("Формат: /respect_grant TELEGRAM_ID СУММА ПРИЧИНА")
            return
        try:
            target_id, amount = int(parts[1]), int(parts[2])
            grant = parts[0].split("@")[0] == "/respect_grant"
            async with factory.begin() as session:
                actor = await current_user(session, message.from_user.id)
                entry = await change_respect(
                    session,
                    actor,
                    target_id,
                    amount,
                    parts[3],
                    grant=grant,
                    idempotency_key=f"message:{message.chat.id}:{message.message_id}",
                )
            await message.answer(
                f"❇: {entry.delta:+d}. Итого: {entry.balance_after}."
            )
        except (ValueError, EconomyError, AccessDenied) as error:
            await message.answer(str(error))

    @router.message(Command("staff"))
    async def staff_command(message: Message, bot: Bot) -> None:
        if not message.from_user:
            return
        parts = (message.text or "").split()
        if len(parts) == 1:
            async with factory.begin() as session:
                actor = await current_user(session, message.from_user.id)
                if actor.staff_role is None:
                    raise AccessDenied("Служебное меню недоступно")
                await delete_quietly(message)
                await upsert_status_card(bot, session, actor, markup=staff_menu(actor))
            return
        if len(parts) != 3 or parts[2].lower() not in ROLE_ALIASES:
            await message.answer(
                "Формат: /staff TELEGRAM_ID lord|magister|tech_priest|watcher|none"
            )
            return
        try:
            async with factory.begin() as session:
                actor = await current_user(session, message.from_user.id)
                target = await current_user(session, int(parts[1]))
                previous_role = target.staff_role
                new_role = ROLE_ALIASES[parts[2].lower()]
                await set_staff_role(session, actor, target, new_role)
                target_id = target.telegram_id
            await delete_quietly(message)
            await message.answer("Служебная роль обновлена.")
            text = (
                message_staff_role_set(new_role)
                if new_role is not None
                else message_staff_role_cleared()
            )
            await bot.send_message(target_id, text)
            token = settings.telegram_bot_token.get_secret_value()
            if new_role is not None and previous_role is None:
                await invite_to_staff_chat(token, settings.staff_chat_id, target_id)
            elif new_role is None and previous_role is not None:
                await kick_from_staff_chat(token, settings.staff_chat_id, target_id)
        except (ValueError, AccessDenied) as error:
            await message.answer(str(error))

    @router.callback_query(F.data == "menu:staff")
    async def staff_menu_callback(callback: CallbackQuery, bot: Bot) -> None:
        if callback.from_user is None:
            return
        async with factory.begin() as session:
            actor = await current_user(session, callback.from_user.id)
            if actor.staff_role is None:
                await callback.answer("Нет доступа", show_alert=True)
                return
            await callback.answer()
            text = (callback.message.text or "") if callback.message else ""
            if text.startswith(("Куда публикуем", "Для какого топика", "Что готовим")):
                await delete_quietly(callback.message)
            await upsert_status_card(bot, session, actor, markup=staff_menu(actor))

    @router.callback_query(F.data == "staff:list")
    async def staff_list_callback(callback: CallbackQuery, bot: Bot) -> None:
        async with factory() as session:
            actor = await current_user(session, callback.from_user.id)
            require_permission(actor, Permission.MANAGE_STAFF)
            users = await list_staff(session)
        lines = [
            f"{user.full_name} — {ROLE_LABELS[user.staff_role]} ({user.telegram_id})"
            for user in users
            if user.staff_role
        ]
        await callback.answer()
        if callback.message:
            notice = await callback.message.answer("\n".join(lines))
            await asyncio.sleep(20)
            await delete_quietly(notice)
            await refresh_home(bot, callback.from_user.id)

    @router.message(Command("setting"))
    async def setting_command(message: Message) -> None:
        if not message.from_user:
            return
        parts = (message.text or "").split()
        if len(parts) != 3:
            await message.answer(
                "Формат: /setting КЛЮЧ ЗНАЧЕНИЕ\n"
                "Ключи: content_silence_days, reminder_hour, transfer_daily_limit, "
                "memes_enabled, interview_enabled"
            )
            return
        try:
            value = int(parts[2])
            if parts[1] == "reminder_hour" and not (
                settings.reminder_window_start <= value < settings.reminder_window_end
            ):
                raise SettingError("Час напоминания должен попадать в разрешённое дневное окно")
            async with factory.begin() as session:
                actor = await current_user(session, message.from_user.id)
                await set_int_setting(session, actor, parts[1], value)
            await delete_quietly(message)
            await message.answer("Настройка сохранена.")
        except (ValueError, AccessDenied, SettingError) as error:
            await message.answer(str(error))

    @router.callback_query(F.data == "staff:settings")
    async def settings_callback(callback: CallbackQuery, bot: Bot) -> None:
        if callback.from_user is None:
            return
        async with factory() as session:
            actor = await current_user(session, callback.from_user.id)
            require_permission(actor, Permission.MANAGE_SETTINGS)
            silence_days = await get_int_setting(
                session,
                "content_silence_days",
                settings.content_silence_days,
            )
            reminder_hour = await get_int_setting(
                session,
                "reminder_hour",
                settings.reminder_hour,
            )
            transfer_limit = await get_int_setting(
                session,
                "transfer_daily_limit",
                settings.transfer_daily_limit,
            )
            memes_enabled = await get_int_setting(
                session, "memes_enabled", setting_default("memes_enabled")
            )
            interview_enabled = await get_int_setting(
                session, "interview_enabled", setting_default("interview_enabled")
            )
        await callback.answer()
        notice = await bot.send_message(
            callback.from_user.id,
            "Настройки публикаций:\n"
            f"content_silence_days = {silence_days}\n"
            f"reminder_hour = {reminder_hour}\n"
            f"transfer_daily_limit = {transfer_limit}\n"
            f"memes_enabled = {memes_enabled}\n"
            f"interview_enabled = {interview_enabled}\n\n"
            "Удобнее менять в админке → Публикации.\n"
            "Или: /setting КЛЮЧ ЗНАЧЕНИЕ",
        )
        await asyncio.sleep(25)
        await delete_quietly(notice)
        await refresh_home(bot, callback.from_user.id)

    @router.callback_query(F.data == "staff:reboot")
    @router.message(Command("reboot"))
    async def reboot_prompt(event: Message | CallbackQuery) -> None:
        if event.from_user is None:
            return
        try:
            async with factory() as session:
                actor = await current_user(session, event.from_user.id)
                require_permission(actor, Permission.MANAGE_SYSTEM)
            status = await check_github_updates(settings)
            text = (
                "Перезагрузка остановит бота, затем watchdog проверит GitHub "
                f"({settings.github_branch}) и при необходимости установит обновления.\n\n"
                f"{status.message}\n"
                f"Текущая сборка: {status.current_sha[:12]}"
            )
            if status.compare_url:
                text += f"\nСравнение: {status.compare_url}"
            markup = reboot_confirm_keyboard()
            if isinstance(event, CallbackQuery):
                await event.answer()
                if event.message:
                    await event.message.answer(text, reply_markup=markup)
            else:
                await event.answer(text, reply_markup=markup)
        except AccessDenied as error:
            if isinstance(event, CallbackQuery):
                await event.answer(str(error), show_alert=True)
            else:
                await event.answer(str(error))

    @router.callback_query(F.data == "reboot:cancel")
    async def reboot_cancel(callback: CallbackQuery) -> None:
        await callback.answer("Отменено")
        if isinstance(callback.message, Message):
            await callback.message.edit_reply_markup(reply_markup=None)

    @router.callback_query(F.data == "reboot:confirm")
    async def reboot_confirm(callback: CallbackQuery) -> None:
        try:
            status = await check_github_updates(settings)
            async with factory.begin() as session:
                actor = await current_user(session, callback.from_user.id)
                await request_restart(
                    session,
                    actor,
                    settings,
                    reason="telegram admin reboot",
                    update_status=status,
                )
            await callback.answer("Запрос принят")
            if isinstance(callback.message, Message):
                await callback.message.edit_text(
                    "Запрос на перезагрузку отправлен watchdog.\n"
                    "Бот скоро перезапустится. После старта придёт отчёт."
                )
        except (AccessDenied, LifecycleError) as error:
            await callback.answer(str(error), show_alert=True)

    @router.message(Command("update_status"))
    async def update_status_command(message: Message) -> None:
        if not message.from_user:
            return
        try:
            async with factory() as session:
                actor = await current_user(session, message.from_user.id)
                require_permission(actor, Permission.MANAGE_SYSTEM)
            status = await check_github_updates(settings)
            text = status.message
            if status.compare_url:
                text += f"\n{status.compare_url}"
            await message.answer(text)
        except AccessDenied as error:
            await message.answer(str(error))

    @router.callback_query(F.data.in_({"staff:new_post"}))
    @router.message(Command("post"))
    async def begin_staff_post(event: Message | CallbackQuery, state: FSMContext, bot: Bot) -> None:
        if event.from_user is None:
            return
        async with factory() as session:
            actor = await current_user(session, event.from_user.id)
            require_permission(actor, Permission.CREATE_STAFF_CONTENT)
        if isinstance(event, CallbackQuery):
            await event.answer()
            await _show_post_topic_chooser(
                bot, event.from_user.id, actor, back_to="menu:staff"
            )
        else:
            await delete_quietly(event)
            await _show_post_topic_chooser(
                bot, event.from_user.id, actor, back_to="menu:staff"
            )

    async def _show_post_mode_chooser(
        bot: Bot,
        telegram_id: int,
        *,
        prefix: str,
        kind_key: str,
        back_to: str,
    ) -> None:
        from aiogram.types import InlineKeyboardButton

        await bot.send_message(
            telegram_id,
            "Как оформим исходник?",
            reply_markup=with_back(
                [
                    [
                        InlineKeyboardButton(
                            text="Интервью",
                            callback_data=f"{prefix}:interview:{kind_key}",
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            text="Свободная форма",
                            callback_data=f"{prefix}:free:{kind_key}",
                        )
                    ],
                ],
                back_to,
            ),
        )

    async def _append_ephemeral(state: FSMContext, *message_ids: int) -> list[int]:
        data = await state.get_data()
        ephemeral = list(data.get("ephemeral_ids") or [])
        for mid in message_ids:
            if mid and mid not in ephemeral:
                ephemeral.append(mid)
        await state.update_data(ephemeral_ids=ephemeral)
        return ephemeral

    async def _send_tracked(
        bot: Bot,
        state: FSMContext,
        chat_id: int,
        text: str,
        *,
        reply_markup=None,
        delete_previous: bool = False,
    ) -> Message:
        data = await state.get_data()
        ephemeral = list(data.get("ephemeral_ids") or [])
        if delete_previous and ephemeral:
            await delete_ids(bot, chat_id, *ephemeral)
            ephemeral = []
        prompt = await bot.send_message(chat_id, text, reply_markup=reply_markup)
        ephemeral.append(prompt.message_id)
        await state.update_data(ephemeral_ids=ephemeral)
        return prompt

    @router.callback_query(
        F.data.in_({"compose:story", "compose:important", "submit:story", "submit:important"})
    )
    async def start_compose_topic(
        callback: CallbackQuery, state: FSMContext, bot: Bot
    ) -> None:
        if callback.from_user is None or callback.data is None:
            return
        kind_key = callback.data.split(":")[-1]
        kind = ContentKind.IMPORTANT if kind_key == "important" else ContentKind.STORY
        prefix = "submit" if callback.data.startswith("submit:") else "compose"
        nav_parent = "submit:post" if prefix == "submit" else "staff:new_post"
        async with factory() as session:
            actor = await current_user(session, callback.from_user.id)
            if kind is ContentKind.IMPORTANT and not _can_propose_important(actor):
                await callback.answer(
                    "Важное только для тёмного лорда и магистра",
                    show_alert=True,
                )
                return
            interview_on = await get_int_setting(
                session, "interview_enabled", setting_default("interview_enabled")
            )
        await callback.answer()
        await delete_quietly(callback.message)
        if not interview_on:
            await _begin_compose(
                bot,
                state,
                callback.from_user.id,
                kind=kind,
                skip_interview=True,
                nav_parent=nav_parent,
            )
            return
        await _show_post_mode_chooser(
            bot,
            callback.from_user.id,
            prefix=prefix,
            kind_key=kind_key,
            back_to=nav_parent,
        )

    @router.callback_query(
        F.data.regexp(r"^(compose|submit):(interview|free):(story|important)$")
    )
    async def start_compose_mode(
        callback: CallbackQuery, state: FSMContext, bot: Bot
    ) -> None:
        if callback.from_user is None or callback.data is None:
            return
        prefix, mode, kind_key = callback.data.split(":")
        kind = ContentKind.IMPORTANT if kind_key == "important" else ContentKind.STORY
        nav_parent = "submit:post" if prefix == "submit" else "staff:new_post"
        async with factory() as session:
            actor = await current_user(session, callback.from_user.id)
            if kind is ContentKind.IMPORTANT and not _can_propose_important(actor):
                await callback.answer(
                    "Важное только для тёмного лорда и магистра",
                    show_alert=True,
                )
                return
        await callback.answer()
        await delete_quietly(callback.message)
        await _begin_compose(
            bot,
            state,
            callback.from_user.id,
            kind=kind,
            skip_interview=(mode == "free"),
            nav_parent=nav_parent,
        )

    async def _begin_compose(
        bot: Bot,
        state: FSMContext,
        telegram_id: int,
        *,
        kind: ContentKind,
        skip_interview: bool,
        nav_parent: str,
    ) -> None:
        from lab21_bot.llm.prompts import (
            INTERVIEW_QUESTIONS,
            interview_disabled_fallback,
            interview_intro,
        )

        back_markup = back_keyboard("flow:cancel_ask")
        await state.set_state(PostComposeState.interview)
        await state.update_data(
            post_kind=kind.value,
            answers=[],
            post_media=[],
            skip_interview=skip_interview,
            nav_parent=nav_parent,
            ephemeral_ids=[],
        )
        if skip_interview:
            text = interview_disabled_fallback()
        else:
            text = interview_intro(question=INTERVIEW_QUESTIONS[0])
        await _send_tracked(bot, state, telegram_id, text, reply_markup=back_markup)

    @router.message(PostComposeState.interview)
    async def compose_interview_answer(message: Message, state: FSMContext, bot: Bot) -> None:
        from lab21_bot.llm.prompts import INTERVIEW_QUESTIONS

        if not message.from_user:
            return
        batch = await albums.collect(message)
        if batch is None:
            return
        payload = _meme_payload_from_messages(batch)
        if payload is None:
            warn = await message.answer(
                "Для заявки на пост принимаются только текст, фото или GIF. "
                "Видео, документы и другое — нет."
            )
            await _append_ephemeral(state, warn.message_id)
            return
        text, media = payload
        data = await state.get_data()
        kind = ContentKind(data["post_kind"])
        collected_media = list(data.get("post_media") or [])
        if media:
            collected_media.extend(media)

        if data.get("skip_interview"):
            if not text and not collected_media:
                warn = await message.answer("Пришлите текст поста и/или фото/GIF.")
                await _append_ephemeral(state, warn.message_id)
                return
            answers = [text] if text else (
                ["(GIF)"]
                if any(m.get("type") == "animation" for m in collected_media)
                else ["(фото)"]
            )
            source = text or answers[0]
        else:
            if not text:
                warn = await message.answer(
                    "Нужен текстовый ответ на вопрос. "
                    "Фото или GIF можно приложить к любому ответу (с подписью) или альбомом."
                )
                await _append_ephemeral(state, warn.message_id)
                return
            answers = [*data.get("answers", []), text]
            if len(answers) < len(INTERVIEW_QUESTIONS):
                await state.update_data(answers=answers, post_media=collected_media)
                await _send_tracked(
                    bot,
                    state,
                    message.chat.id,
                    INTERVIEW_QUESTIONS[len(answers)],
                    reply_markup=back_keyboard("flow:cancel_ask"),
                    delete_previous=True,
                )
                return
            source = format_interview_source(answers, INTERVIEW_QUESTIONS)

        data = await state.get_data()
        ephemeral = list(data.get("ephemeral_ids") or [])
        wait = await message.answer("Отправляю исходник на модерацию…")
        try:
            async with factory.begin() as session:
                actor = await current_user(session, message.from_user.id)
                item = await submit_for_moderation(
                    session,
                    actor,
                    kind,
                    source,
                    source,
                    media=collected_media,
                    llm_processed=False,
                )
                await upsert_status_card(bot, session, actor)
                photo_note = (
                    f" · фото: {len(collected_media)}" if collected_media else ""
                )
                media_bit = (
                    f", вложений: {len(collected_media)}" if collected_media else ""
                )
                await notify_admin_event(
                    session,
                    settings,
                    "content_queue",
                    title=f"Новая заявка #{item.id} ({kind.value})",
                    body=(
                        f"От {actor.full_name} "
                        f"(ожидает одобрения к генерации{media_bit})."
                    ),
                    link="/publications",
                    bot=bot,
                )
            await state.clear()
            if ephemeral:
                await delete_ids(bot, message.chat.id, *ephemeral)
            await wait.edit_text(
                f"Заявка #{item.id} в очереди{photo_note}.\n"
                "Исходник без LLM — после первого одобрения staff запустит оформление."
            )
            await asyncio.sleep(12)
            await delete_quietly(wait)
            await refresh_home(bot, message.from_user.id)
        except (AccessDenied, ContentError, ValueError) as error:
            await wait.edit_text(str(error))

    @router.callback_query(F.data.startswith("content:regen:"))
    async def regenerate_content(callback: CallbackQuery, bot: Bot) -> None:
        item_id = int(callback.data.split(":")[-1])  # type: ignore[union-attr]
        try:
            async with factory() as session:
                actor = await current_user(session, callback.from_user.id)
                require_permission(actor, Permission.CREATE_STAFF_CONTENT)
                item = await session.get(ContentItem, item_id)
                if item is None:
                    raise ContentError("Черновик не найден")
                if item.status is ContentStatus.PUBLISHED:
                    raise ContentError("Уже опубликовано")
                source = item.source_text
                runtime = await get_llm_runtime(session, settings)
            generated = await llm.generate_staff_post(
                source,
                interview=source.lstrip().startswith("Q:"),
                job=source.lstrip().startswith("JOB:"),
                runtime=runtime,
            )
            async with factory.begin() as session:
                item = await mark_llm_draft(session, item_id, generated)
                await notify_admin_event(
                    session,
                    settings,
                    "llm_done",
                    title=f"LLM-черновик готов #{item_id}",
                    body="Проверьте перед публикацией.",
                    link=f"/publications#item-{item_id}",
                    bot=bot,
                )
            await callback.answer("Готово")
            if isinstance(callback.message, Message):
                await callback.message.edit_text(
                    generated, reply_markup=content_actions(item, staff_draft=True)
                )
        except (AccessDenied, ContentError, LLMError) as error:
            await callback.answer(str(error), show_alert=True)

    @router.callback_query(F.data.startswith("content:edit:"))
    async def begin_content_edit(callback: CallbackQuery, state: FSMContext) -> None:
        item_id = int(callback.data.split(":")[-1])  # type: ignore[union-attr]
        async with factory() as session:
            actor = await current_user(session, callback.from_user.id)
            item = await session.get(ContentItem, item_id)
            if item is None:
                await callback.answer("Материал не найден", show_alert=True)
                return
            if item.author_id != actor.telegram_id and not has_permission(
                actor, Permission.MODERATE_CONTENT
            ):
                await callback.answer("Нет доступа", show_alert=True)
                return
        await state.set_state(EditContentState.text)
        await state.update_data(item_id=item_id, nav_parent="menu:home")
        await callback.answer()
        if callback.message:
            prompt = await callback.message.answer(
                "Пришлите новую версию текста целиком.",
                reply_markup=back_keyboard("flow:cancel_ask"),
            )
            await state.update_data(ephemeral_ids=[prompt.message_id])

    @router.message(EditContentState.text, F.text)
    async def save_content_edit(message: Message, state: FSMContext) -> None:
        data = await state.get_data()
        async with factory.begin() as session:
            item = await session.get(ContentItem, int(data["item_id"]), with_for_update=True)
            if item is None:
                raise ContentError("Материал не найден")
            item.draft_text = message.text
        await state.clear()
        await message.answer("Текст обновлён.", reply_markup=content_actions(item))

    @router.callback_query(F.data.startswith("content:publish:"))
    async def publish_content(callback: CallbackQuery, bot: Bot) -> None:
        item_id = int(callback.data.split(":")[-1])  # type: ignore[union-attr]
        try:
            token = settings.telegram_bot_token.get_secret_value()
            async with factory.begin() as session:
                actor = await current_user(session, callback.from_user.id)
                require_permission(actor, Permission.MODERATE_CONTENT)
                item = await publish_content_item(
                    session,
                    token,
                    settings,
                    item_id,
                    reviewer=actor,
                )
                await maybe_send_flood_teaser(
                    session,
                    token,
                    flood_destination(settings),
                    item,
                    item.author,
                    story_thread_id=settings.main_thread_id,
                )
            await callback.answer("Опубликовано")
            if isinstance(callback.message, Message):
                await callback.message.edit_reply_markup(reply_markup=None)
        except (AccessDenied, ContentError) as error:
            await callback.answer(str(error), show_alert=True)

    @router.callback_query(F.data.regexp(r"^content:(info|reject):\d+$"))
    async def reject_or_request(callback: CallbackQuery, bot: Bot) -> None:
        _, action, raw_id = callback.data.split(":")  # type: ignore[union-attr]
        status = ContentStatus.NEEDS_INFO if action == "info" else ContentStatus.REJECTED
        try:
            async with factory.begin() as session:
                reviewer = await current_user(session, callback.from_user.id)
                item = await moderate_content(session, reviewer, int(raw_id), status)
                author_id = item.author_id
                reject_text = (
                    "Смотрящий просит дополнить материал."
                    if action == "info"
                    else message_content_rejected(reviewer=reviewer)
                )
            await bot.send_message(
                author_id,
                reject_text,
                parse_mode="HTML" if action == "reject" else None,
            )
            await callback.answer("Статус обновлён")
            if isinstance(callback.message, Message):
                await callback.message.edit_reply_markup(reply_markup=None)
        except (AccessDenied, ContentError) as error:
            await callback.answer(str(error), show_alert=True)

    @router.callback_query(F.data == "menu:submit")
    async def choose_submission(callback: CallbackQuery, bot: Bot) -> None:
        if callback.from_user is None:
            return
        await callback.answer()
        text = (callback.message.text or "") if callback.message else ""
        if text.startswith(("Для какого топика", "Куда публикуем")):
            await delete_quietly(callback.message)
        await _show_submit_chooser(bot, callback.from_user.id)

    @router.callback_query(F.data == "submit:post")
    async def choose_post_topic(callback: CallbackQuery, bot: Bot) -> None:
        if callback.from_user is None:
            return
        async with factory() as session:
            user = await current_user(session, callback.from_user.id)
        await callback.answer()
        await delete_quietly(callback.message)
        await _show_post_topic_chooser(
            bot, callback.from_user.id, user, back_to="menu:submit"
        )

    @router.callback_query(F.data == "submit:meme")
    async def begin_meme_submission(callback: CallbackQuery, state: FSMContext, bot: Bot) -> None:
        if callback.from_user is None:
            return
        async with factory() as session:
            if not await get_int_setting(
                session, "memes_enabled", setting_default("memes_enabled")
            ):
                await callback.answer("Мемы сейчас отключены", show_alert=True)
                return
        await state.set_state(SubmissionState.meme)
        await state.update_data(nav_parent="menu:submit")
        await callback.answer()
        await delete_quietly(callback.message)
        prompt = await bot.send_message(
            callback.from_user.id,
            "Пришлите мем: текст, фото или GIF (с подписью или без).",
            reply_markup=back_keyboard("flow:cancel_ask"),
        )
        await state.update_data(ephemeral_ids=[prompt.message_id])

    @router.message(SubmissionState.meme)
    async def receive_meme(message: Message, state: FSMContext, bot: Bot) -> None:
        if not message.from_user:
            return
        messages = await albums.collect(message)
        if messages is None:
            return
        payload = _meme_payload_from_messages(messages)
        if payload is None:
            await message.answer(
                "Для мема принимаются только текст, фото или GIF. Видео и другое — нет."
            )
            return
        text, media = payload
        if not text and media:
            text = "(GIF)" if any(m.get("type") == "animation" for m in media) else "(фото)"
        data = await state.get_data()
        ephemeral = list(data.get("ephemeral_ids", []))
        async with factory.begin() as session:
            author = await current_user(session, message.from_user.id)
            if not await get_int_setting(
                session, "memes_enabled", setting_default("memes_enabled")
            ):
                await message.answer("Мемы сейчас отключены.")
                return
            item = await submit_community_content(
                session, author, ContentKind.MEME, text or "(фото)", media
            )
            await upsert_status_card(bot, session, author)
            await notify_admin_event(
                session,
                settings,
                "content_queue",
                title=f"Новый мем #{item.id}",
                body=f"От {author.full_name} — в очереди модерации.",
                link="/publications/memes",
                bot=bot,
            )
        await state.clear()
        await delete_ids(bot, message.chat.id, *ephemeral)
        notice = await message.answer(f"Мем #{item.id} отправлен на модерацию.")
        await asyncio.sleep(8)
        await delete_quietly(notice)
        await refresh_home(bot, message.from_user.id)

    @router.callback_query(F.data == "staff:moderation")
    async def moderation_queue(callback: CallbackQuery, bot: Bot) -> None:
        async with factory() as session:
            actor = await current_user(session, callback.from_user.id)
            require_permission(actor, Permission.MODERATE_CONTENT)
            items = await list_moderation_queue(session, limit=10)
        await callback.answer()
        if not callback.message:
            return
        if not items:
            await callback.message.answer(
                "Очередь пуста. Смотрите также админку → Публикации."
            )
            return
        for item in items:
            await _send_review_item(bot, callback.message.chat.id, item)

    @router.callback_query(F.data.regexp(r"^order:(approve|cancel):\d+$"))
    async def order_resolution(callback: CallbackQuery, bot: Bot) -> None:
        _, action, raw_id = callback.data.split(":")  # type: ignore[union-attr]
        try:
            async with factory.begin() as session:
                actor = await current_user(session, callback.from_user.id)
                order, granted_rank = await resolve_order(
                    session, actor, int(raw_id), approve=action == "approve"
                )
                buyer_id = order.buyer_id
                order_id = order.id
                fulfilled = order.status is OrderStatus.FULFILLED
                if not fulfilled and order.product is not None:
                    await sync_shop_card(
                        bot, order.product, settings, upload_dir=settings.upload_dir
                    )
            if fulfilled:
                text = message_order_fulfilled(order_id=order_id, new_rank=granted_rank)
            else:
                text = message_order_cancelled(order_id=order_id)
            await bot.send_message(buyer_id, text)
            await callback.answer("Заказ обработан")
            if isinstance(callback.message, Message):
                await callback.message.edit_reply_markup(reply_markup=None)
        except (AccessDenied, EconomyError) as error:
            await callback.answer(str(error), show_alert=True)

    @router.callback_query(F.data == "staff:orders")
    async def pending_orders(callback: CallbackQuery) -> None:
        async with factory() as session:
            actor = await current_user(session, callback.from_user.id)
            require_permission(actor, Permission.MODERATE_ORDERS)
            orders = list(
                await session.scalars(
                    select(Order)
                    .where(Order.status == OrderStatus.PENDING)
                    .options(selectinload(Order.product))
                    .order_by(Order.created_at)
                    .limit(10)
                )
            )
        await callback.answer()
        if callback.message:
            if not orders:
                await callback.message.answer("Необработанных заказов нет.")
            for order in orders:
                await callback.message.answer(
                    f"Заказ #{order.id}: {order.product.name}, {order.total_price} 🙏",
                    reply_markup=order_actions(order),
                )

    @router.message(Command("product"))
    async def product_command(message: Message, bot: Bot) -> None:
        if not message.from_user:
            return
        raw = (message.text or "").partition(" ")[2]
        parts = [part.strip() for part in raw.split("|")]
        if len(parts) < 5:
            await message.answer(
                "Формат: /product артикул | название | описание | цена | остаток/inf | "
                "novice/adept | merch/device/service"
            )
            return
        try:
            price = int(parts[3])
            stock = None if parts[4].lower() == "inf" else int(parts[4])
            min_rank = CommunityRank(parts[5]) if len(parts) > 5 else CommunityRank.NOVICE
            kind = ProductKind(parts[6]) if len(parts) > 6 else ProductKind.MERCH
            async with factory.begin() as session:
                actor = await current_user(session, message.from_user.id)
                product = await create_product(
                    session,
                    actor,
                    article=parts[0],
                    name=parts[1],
                    description=parts[2],
                    price=price,
                    stock=stock,
                    min_rank=min_rank,
                    kind=kind,
                )
                await sync_shop_card(bot, product, settings, upload_dir=settings.upload_dir)
                article = product.article
                product_id = product.id
            await message.answer(f"Товар [{article}] #{product_id} создан.")
        except (ValueError, EconomyError, AccessDenied) as error:
            await message.answer(str(error))

    @router.message(Command("product_edit"))
    async def product_edit_command(message: Message, bot: Bot) -> None:
        if not message.from_user:
            return
        parts = (message.text or "").split(maxsplit=3)
        if len(parts) != 4:
            await message.answer("Формат: /product_edit ID ПОЛЕ ЗНАЧЕНИЕ")
            return
        try:
            async with factory.begin() as session:
                actor = await current_user(session, message.from_user.id)
                product = await update_product(
                    session,
                    actor,
                    int(parts[1]),
                    parts[2],
                    parts[3],
                )
                await sync_shop_card(bot, product, settings, upload_dir=settings.upload_dir)
                article = product.article
                product_id = product.id
            await message.answer(f"Товар [{article}] #{product_id} обновлён.")
        except (ValueError, EconomyError, AccessDenied) as error:
            await message.answer(str(error))

    @router.message_reaction_count()
    async def reaction_count_updated(event: MessageReactionCountUpdated) -> None:
        total = sum(item.total_count for item in event.reactions)
        async with factory.begin() as session:
            await sync_post_reaction_total(
                session,
                chat_id=event.chat.id,
                message_id=event.message_id,
                total_reactions=total,
            )

    @router.message_reaction()
    async def reaction_updated(event: MessageReactionUpdated) -> None:
        delta = len(event.new_reaction or []) - len(event.old_reaction or [])
        if delta == 0:
            return
        async with factory.begin() as session:
            await apply_post_reaction_delta(
                session,
                chat_id=event.chat.id,
                message_id=event.message_id,
                delta=delta,
            )

    @router.message(F.chat.type.in_({"group", "supergroup"}), FeedbackIntakeFilter())
    async def feedback_channel_intake(message: Message, bot: Bot) -> None:
        """Capture /bug and /upgrade posts from the bugs topic into admin queue."""
        thread_id = getattr(message, "message_thread_id", None)
        if not matches_bugs_destination(
            settings, chat_id=message.chat.id, thread_id=thread_id
        ):
            return
        batch = await albums.collect(message)
        if batch is None:
            return
        lead = batch[0]
        kind = detect_feedback_kind(lead.text or lead.caption)
        if kind is None:
            return
        media: list[dict] = []
        for item in batch:
            media.extend(media_from_telegram_message(item))
        # de-dupe file_ids
        seen: set[str] = set()
        unique_media: list[dict] = []
        for entry in media:
            fid = str(entry.get("file_id") or "")
            if not fid or fid in seen:
                continue
            seen.add(fid)
            unique_media.append(entry)
        text = clean_feedback_text(lead.text or lead.caption)
        author_name = lead.from_user.full_name if lead.from_user else "Unknown"
        author_username = lead.from_user.username if lead.from_user else None
        author_tg_id = lead.from_user.id if lead.from_user else None
        try:
            async with factory.begin() as session:
                author = None
                if author_tg_id is not None:
                    author = await session.get(User, author_tg_id)
                    if author is None:
                        author = await register_user(
                            session,
                            author_tg_id,
                            author_name,
                            author_username,
                        )
                row = await create_feedback_report(
                    session,
                    kind=kind,
                    chat_id=lead.chat.id,
                    message_id=lead.message_id,
                    message_thread_id=thread_id,
                    text=text,
                    media=unique_media,
                    author=author,
                    author_name=author_name,
                    author_username=author_username,
                )
                if row is None:
                    return
                await notify_admin_event(
                    session,
                    settings,
                    "feedback",
                    title=f"{'Баг' if kind.value == 'bug' else 'Предложение'} #{row.id}",
                    body=text[:400] or "(медиа)",
                    link=(
                        "/feedback/bugs"
                        if kind.value == "bug"
                        else "/feedback/upgrades"
                    ),
                    bot=bot,
                )
            from aiogram.types import ReactionTypeEmoji

            try:
                await bot.set_message_reaction(
                    lead.chat.id,
                    lead.message_id,
                    [ReactionTypeEmoji(emoji=REACTION_PENDING)],
                )
            except (TelegramBadRequest, TelegramForbiddenError):
                pass
        except Exception:
            logger = structlog.get_logger(__name__)
            logger.exception("feedback_intake_failed")

    @router.message(F.chat.type.in_({"group", "supergroup"}), BotMentionedFilter())
    async def mention_reply(message: Message, bot: Bot) -> None:
        me = await bot.get_me()
        username = settings.telegram_bot_username or me.username
        if not message_mentions_bot(message, bot_id=me.id, bot_username=username):
            return
        if not message.from_user:
            return
        key = f"mention:{message.from_user.id}"
        async with factory() as session:
            cooldown = await get_int_setting(
                session,
                "mention_cooldown_seconds",
                int(setting_default("mention_cooldown_seconds")),
            )
            season = await active_season(session)
            phrases_key = season.phrases_key if season is not None else None
        remaining = cooldown_remaining(key)
        if remaining > 0:
            try:
                await message.reply(phrase("presence", "cooldown"))
            except (TelegramBadRequest, TelegramForbiddenError):
                pass
            return
        set_cooldown(key, float(cooldown))
        reply = pick_mention_reply(phrases_key=phrases_key or None)
        if not reply:
            return
        try:
            await message.reply(reply)
        except (TelegramBadRequest, TelegramForbiddenError):
            pass

    @router.message(F.chat.type.in_({"group", "supergroup"}), ForumTopicTrackedFilter())
    async def forum_topic_activity(message: Message, bot: Bot) -> None:
        """Track «Будни» silence and mirror «Важное» → флудилка for forum topics."""
        chat_id = message.chat.id
        thread_id = message.message_thread_id
        if matches_destination(
            settings,
            chat_id=chat_id,
            thread_id=thread_id,
            kind=ContentKind.STORY,
        ):
            async with factory.begin() as session:
                await record_channel_post(session, settings.main_channel_id, message.message_id)
            return

        if not matches_destination(
            settings,
            chat_id=chat_id,
            thread_id=thread_id,
            kind=ContentKind.IMPORTANT,
        ):
            return

        flood = flood_destination(settings)
        if flood is None:
            return
        text = message.text or message.caption or ""
        prefix = "📌 Из «Важное»"
        body = f"{prefix}\n\n{text}".strip() if text else prefix
        thread_kwargs = (
            {"message_thread_id": flood.thread_id} if flood.thread_id is not None else {}
        )
        try:
            if message.photo:
                await bot.send_photo(
                    flood.chat_id,
                    message.photo[-1].file_id,
                    caption=body[:1024],
                    **thread_kwargs,
                )
            elif message.video:
                await bot.send_video(
                    flood.chat_id,
                    message.video.file_id,
                    caption=body[:1024],
                    **thread_kwargs,
                )
            else:
                await bot.send_message(flood.chat_id, body, **thread_kwargs)
        except (TelegramBadRequest, TelegramForbiddenError):
            pass

    @router.channel_post()
    async def channel_activity(message: Message, bot: Bot) -> None:
        """Legacy path for separate channels (non-forum)."""
        chat_id = message.chat.id
        if chat_id == settings.main_channel_id and settings.main_thread_id is None:
            async with factory.begin() as session:
                await record_channel_post(session, settings.main_channel_id, message.message_id)
            return
        if (
            settings.important_channel_id
            and chat_id == settings.important_channel_id
            and settings.important_thread_id is None
        ):
            flood = flood_destination(settings)
            if flood is None:
                return
            text = message.text or message.caption or ""
            prefix = "📌 Из канала «Важное»"
            body = f"{prefix}\n\n{text}".strip() if text else prefix
            thread_kwargs = (
                {"message_thread_id": flood.thread_id} if flood.thread_id is not None else {}
            )
            try:
                if message.photo:
                    await bot.send_photo(
                        flood.chat_id,
                        message.photo[-1].file_id,
                        caption=body[:1024],
                        **thread_kwargs,
                    )
                elif message.video:
                    await bot.send_video(
                        flood.chat_id,
                        message.video.file_id,
                        caption=body[:1024],
                        **thread_kwargs,
                    )
                else:
                    await bot.send_message(flood.chat_id, body, **thread_kwargs)
            except (TelegramBadRequest, TelegramForbiddenError):
                pass

    @router.message(F.chat.type == "private")
    async def interview_answer_legacy(message: Message, bot: Bot) -> None:
        """Legacy DB interviews from older silence flow — finish into moderation queue."""
        from lab21_bot.llm.prompts import INTERVIEW_QUESTIONS

        if not message.from_user or not message.text or message.text.startswith("/"):
            return
        async with factory.begin() as session:
            interview = await session.scalar(
                select(Interview)
                .where(
                    Interview.employee_id == message.from_user.id,
                    Interview.state == "prompted",
                )
                .order_by(Interview.prompted_at.desc())
                .limit(1)
                .with_for_update()
            )
            if interview is None:
                return
            answers = [*interview.answers, message.text]
            interview.answers = answers
            if len(answers) < len(INTERVIEW_QUESTIONS):
                question_index = len(answers)
            else:
                interview.state = "generating"
                question_index = -1
        if question_index >= 0:
            await message.answer(INTERVIEW_QUESTIONS[question_index])
            return
        source = format_interview_source(answers, INTERVIEW_QUESTIONS)
        try:
            async with factory.begin() as session:
                actor = await current_user(session, message.from_user.id)
                item = await submit_for_moderation(
                    session,
                    actor,
                    ContentKind.STORY,
                    source,
                    source,
                    llm_processed=False,
                )
                interview = await session.scalar(
                    select(Interview)
                    .where(
                        Interview.employee_id == message.from_user.id,
                        Interview.state == "generating",
                    )
                    .order_by(Interview.prompted_at.desc())
                    .limit(1)
                    .with_for_update()
                )
                if interview:
                    interview.state = "completed"
                    interview.content_item_id = item.id
                    interview.completed_at = datetime.now(UTC)
                await notify_admin_event(
                    session,
                    settings,
                    "content_queue",
                    title=f"Новая заявка #{item.id} (story)",
                    body=(
                        f"{actor.full_name} завершил интервью "
                        "(ожидает одобрения к генерации)."
                    ),
                    link="/publications",
                    bot=bot,
                )
            await message.answer(
                f"Заявка #{item.id} в очереди.\n"
                "Исходник без LLM — после одобрения staff запустит оформление."
            )
        except (AccessDenied, ContentError) as error:
            async with factory.begin() as session:
                failed = await session.scalar(
                    select(Interview)
                    .where(
                        Interview.employee_id == message.from_user.id,
                        Interview.state == "generating",
                    )
                    .order_by(Interview.prompted_at.desc())
                    .limit(1)
                    .with_for_update()
                )
                if failed:
                    failed.state = "prompted"
            await message.answer(str(error))

    return router
