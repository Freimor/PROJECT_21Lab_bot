from __future__ import annotations

from html import escape

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.types import InlineKeyboardMarkup, Message
from sqlalchemy.ext.asyncio import AsyncSession

from lab21_bot.data import phrase, rank_label, respect_prefix, role_label, skill_title
from lab21_bot.keyboards import main_menu
from lab21_bot.models import User
from lab21_bot.services.content import count_user_publications

_BIO_MAX_LEN = 500
_BIO_PLACEHOLDER = "Участник немногословен..."
_SYSTEM_BIO_MARKERS = (
    "запрос участника на добавление навыка",
    "запрос на добавление навыка",
    "назначено при принятии в сообщество",
    "требуется валидация",
)


def _skills_line(user: User) -> str:
    ids = list(user.skill_ids or [])
    if not ids:
        return "—"
    return ", ".join(skill_title(sid) for sid in ids)


def _skills_block(user: User) -> str:
    ids = list(user.skill_ids or [])
    if not ids:
        return "—"
    return "\n".join(f"• {escape(skill_title(sid))}" for sid in ids)


def _joined_on(user: User) -> str:
    started = user.started_at
    if started is None:
        return "—"
    return started.astimezone().strftime("%d.%m.%Y")


def _open_to_jobs_label(user: User) -> str:
    return "да" if user.job_notify_enabled else "нет"


def display_bio(user: User) -> str:
    """Public «О себе» text; ignore empty / leaked system notes."""
    raw = (user.bio or "").strip()
    if not raw:
        return _BIO_PLACEHOLDER
    lowered = raw.casefold()
    if any(marker in lowered for marker in _SYSTEM_BIO_MARKERS):
        return _BIO_PLACEHOLDER
    return raw


def status_text(user: User, *, posts: int = 0) -> str:
    if user.staff_role is not None:
        return phrase(
            "status",
            "staff",
            role=role_label(str(user.staff_role)),
            memes=user.approved_meme_count,
        )
    return phrase(
        "status",
        "member",
        rank=rank_label(str(user.rank)),
        prefix=respect_prefix(int(user.respect or 0)),
        balance=user.balance,
        respect=user.respect,
        posts=int(posts),
        skills=_skills_line(user),
        open_jobs=_open_to_jobs_label(user),
    )


def profile_card_html(
    user: User,
    *,
    jobs_done: int = 0,
    posts: int = 0,
) -> str:
    name = escape(user.full_name)
    if user.staff_role is not None:
        return phrase(
            "status",
            "card_staff",
            name=name,
            role=escape(role_label(str(user.staff_role))),
            memes=user.approved_meme_count,
            joined=_joined_on(user),
            bio=escape(display_bio(user)),
        )
    prefix = respect_prefix(int(user.respect or 0))
    rank_key = getattr(user.rank, "value", None) or user.rank or "novice"
    rank = rank_label(str(rank_key)) or "Послушник"
    title = f"{prefix} {rank}".strip().lower()
    return phrase(
        "status",
        "card_member",
        name=name,
        title=escape(title),
        respect=int(user.respect or 0),
        skills=_skills_block(user),
        jobs_done=int(jobs_done),
        posts=int(posts),
        open_jobs=_open_to_jobs_label(user),
        bio=escape(display_bio(user)),
        joined=_joined_on(user),
    )


def normalize_bio(text: str) -> str:
    cleaned = " ".join((text or "").split())
    if len(cleaned) > _BIO_MAX_LEN:
        raise ValueError(f"Слишком длинно. Максимум {_BIO_MAX_LEN} символов.")
    return cleaned


async def send_profile_card(
    bot: Bot,
    chat_id: int,
    user: User,
    *,
    jobs_done: int = 0,
    posts: int = 0,
    reply_markup: InlineKeyboardMarkup | None = None,
) -> Message | None:
    html = profile_card_html(user, jobs_done=jobs_done, posts=posts)
    try:
        if user.avatar_file_id:
            return await bot.send_photo(
                chat_id,
                user.avatar_file_id,
                caption=html[:1024],
                parse_mode="HTML",
                reply_markup=reply_markup,
            )
        return await bot.send_message(
            chat_id,
            html,
            parse_mode="HTML",
            reply_markup=reply_markup,
        )
    except (TelegramBadRequest, TelegramForbiddenError):
        try:
            return await bot.send_message(
                chat_id,
                html,
                parse_mode="HTML",
                reply_markup=reply_markup,
            )
        except (TelegramBadRequest, TelegramForbiddenError):
            return None


async def delete_quietly(*messages: Message | None) -> None:
    for message in messages:
        if message is None:
            continue
        try:
            await message.delete()
        except (TelegramBadRequest, TelegramForbiddenError):
            pass


async def delete_ids(bot: Bot, chat_id: int, *message_ids: int | None) -> None:
    for message_id in message_ids:
        if message_id is None:
            continue
        try:
            await bot.delete_message(chat_id, message_id)
        except (TelegramBadRequest, TelegramForbiddenError):
            pass


async def upsert_status_card(
    bot: Bot,
    session: AsyncSession,
    user: User,
    *,
    with_menu: bool = True,
    markup: InlineKeyboardMarkup | None = None,
) -> Message | None:
    posts = await count_user_publications(session, user.telegram_id)
    text = status_text(user, posts=posts)
    keyboard = markup if markup is not None else (main_menu(user) if with_menu else None)
    chat_id = user.telegram_id

    if user.status_message_id is not None:
        try:
            await bot.edit_message_text(
                text,
                chat_id=chat_id,
                message_id=user.status_message_id,
                reply_markup=keyboard,
            )
            return None
        except TelegramBadRequest:
            await delete_ids(bot, chat_id, user.status_message_id)
            user.status_message_id = None

    try:
        sent = await bot.send_message(chat_id, text, reply_markup=keyboard)
    except (TelegramBadRequest, TelegramForbiddenError):
        return None
    user.status_message_id = sent.message_id
    await session.flush()
    return sent
