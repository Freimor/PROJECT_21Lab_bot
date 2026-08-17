"""Publish service jobs to forum topic and notify opted-in members."""

from __future__ import annotations

from html import escape
from typing import Any

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from sqlalchemy.ext.asyncio import AsyncSession

from lab21_bot.data import phrase, skill_title
from lab21_bot.keyboards import job_board_keyboard
from lab21_bot.models import ServiceJob, ServiceJobStatus, User
from lab21_bot.services.destinations import job_destination
from lab21_bot.services.jobs import list_job_notify_targets, set_job_message


def format_job_post_html(job: ServiceJob, customer: User, *, done: bool = False) -> str:
    skills = ", ".join(escape(skill_title(sid)) for sid in (job.skill_ids or []))
    desc = escape(job.description.strip())
    # Meme-style attribution: italic display name, no @ ping.
    label = escape((customer.full_name or "").strip() or customer.username or "заказчик")
    title = "<b>✅ Заказ выполнен</b>" if done else "<b>Заказ на работу</b>"
    lines = [
        title,
        f"Навыки: <b>{skills or '—'}</b>",
        f"Оплата: <b>{job.price}</b> 🙏",
        f"Исполнителю: <b>{job.respect_reward}</b> ❇",
        "",
        desc,
        "",
        f"— <i>{label}</i>",
        f"#{job.id}",
    ]
    return "\n".join(lines)


def _job_has_photo(job: ServiceJob) -> bool:
    media = list(job.media or [])
    return bool(media and media[0].get("type") == "photo" and media[0].get("file_id"))


async def sync_job_board_post(
    bot: Bot,
    job: ServiceJob,
    customer: User | None = None,
    *,
    update_text: bool = False,
) -> None:
    """Update the Заказы post keyboard (and optionally the body) to match job status."""
    chat_id = job.job_chat_id
    message_id = job.job_message_id
    if not chat_id or not message_id:
        return
    markup = job_board_keyboard(job.id, job.status)
    if update_text and customer is not None:
        done = job.status is ServiceJobStatus.DONE
        text = format_job_post_html(job, customer, done=done)
        try:
            if _job_has_photo(job):
                await bot.edit_message_caption(
                    chat_id=chat_id,
                    message_id=message_id,
                    caption=text[:1024],
                    parse_mode="HTML",
                    reply_markup=markup,
                )
            else:
                await bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=message_id,
                    text=text,
                    parse_mode="HTML",
                    reply_markup=markup,
                )
            return
        except (TelegramBadRequest, TelegramForbiddenError):
            pass
    try:
        await bot.edit_message_reply_markup(
            chat_id=chat_id,
            message_id=message_id,
            reply_markup=markup,
        )
    except (TelegramBadRequest, TelegramForbiddenError):
        pass


async def mark_job_board_done(
    bot: Bot,
    job: ServiceJob,
    customer: User,
) -> None:
    """Show completed state on the Заказы post after customer confirms."""
    await sync_job_board_post(bot, job, customer, update_text=True)


async def publish_service_job(
    bot: Bot,
    session: AsyncSession,
    settings: Any,
    job: ServiceJob,
    customer: User,
) -> int | None:
    dest = job_destination(settings)
    if dest is None:
        return None
    text = format_job_post_html(job, customer)
    markup = job_board_keyboard(job.id, job.status)
    thread_kwargs = (
        {"message_thread_id": dest.thread_id} if dest.thread_id is not None else {}
    )
    media = list(job.media or [])
    try:
        if media:
            first = media[0]
            file_id = first.get("file_id")
            kind = first.get("type", "photo")
            if file_id and kind == "photo":
                sent = await bot.send_photo(
                    dest.chat_id,
                    file_id,
                    caption=text[:1024],
                    parse_mode="HTML",
                    reply_markup=markup,
                    **thread_kwargs,
                )
            else:
                sent = await bot.send_message(
                    dest.chat_id,
                    text,
                    parse_mode="HTML",
                    reply_markup=markup,
                    **thread_kwargs,
                )
        else:
            sent = await bot.send_message(
                dest.chat_id,
                text,
                parse_mode="HTML",
                reply_markup=markup,
                **thread_kwargs,
            )
    except (TelegramBadRequest, TelegramForbiddenError):
        return None
    await set_job_message(session, job, chat_id=dest.chat_id, message_id=sent.message_id)
    return sent.message_id


async def notify_job_subscribers(
    bot: Bot,
    session: AsyncSession,
    job: ServiceJob,
) -> None:
    targets = await list_job_notify_targets(
        session,
        list(job.skill_ids or []),
        exclude_user_id=job.customer_id,
    )
    skill_line = ", ".join(skill_title(sid) for sid in (job.skill_ids or []))
    text = phrase(
        "jobs",
        "notify",
        skill=skill_line,
        job_id=job.id,
        price=job.price,
        respect=job.respect_reward,
    )
    for user in targets:
        try:
            await bot.send_message(user.telegram_id, text)
        except (TelegramBadRequest, TelegramForbiddenError):
            continue
