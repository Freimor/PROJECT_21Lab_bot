"""Карточка ярмарки в топике Telegram. Публикуется, когда на складе есть остаток."""

from __future__ import annotations

from html import escape
from pathlib import Path
from typing import Any

import structlog
from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.types import FSInputFile, InlineKeyboardButton, InlineKeyboardMarkup

from lab21_bot.models import Listing
from lab21_bot.services.destinations import fair_destination
from lab21_bot.services.marketplace import available, price_label
from lab21_bot.telegram_client import create_bot

logger = structlog.get_logger(__name__)
_CAPTION_LIMIT = 1024


def _author(listing: Listing) -> str:
    if listing.seller_id is None:
        return "21Lab"
    seller = listing.__dict__.get("seller")
    if seller is not None and getattr(seller, "full_name", None):
        return str(seller.full_name)
    return "участник"


def format_fair_card_html(listing: Listing, *, author: str) -> str:
    lines = [
        "<b>Ярмарка</b>",
        f"<b>{escape(listing.title)}</b>",
        "",
        escape((listing.summary or "").strip()),
        "",
        f"Цена: <b>{escape(price_label(listing))}</b>",
        f"На складе: {listing.stock}",
        f"Можно забрать: {available(listing)}",
        f"Автор: {escape(author)}",
    ]
    if listing.stock <= 0:
        lines.extend(["", "<i>Нет на складе</i>"])
    html = "\n".join(lines)
    return html[:_CAPTION_LIMIT]


def _keyboard(listing: Listing, settings: Any) -> InlineKeyboardMarkup | None:
    base = getattr(settings, "miniapp_base_url", None)
    if not base:
        return None
    url = f"{str(base).rstrip('/')}/#/market/{listing.id}"
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="Открыть карточку", url=url)]]
    )


def _photo(listing: Listing, upload_dir: str | Path | None) -> FSInputFile | None:
    photos = list(listing.photos or [])
    if not photos or not upload_dir:
        return None
    path = Path(upload_dir) / photos[0]
    if not path.is_file():
        return None
    return FSInputFile(path)


async def sync_fair_card(bot: Bot, listing: Listing, settings: Any) -> None:
    dest = fair_destination(settings)
    if dest is None:
        return
    removed = str(getattr(listing.status, "value", listing.status)) == "removed"
    if listing.fair_message_id and removed:
        await _delete(bot, listing)
        return
    if int(listing.stock) <= 0 and not listing.fair_message_id:
        return
    html = format_fair_card_html(listing, author=_author(listing))
    markup = _keyboard(listing, settings)
    try:
        if listing.fair_chat_id and listing.fair_message_id:
            if listing.fair_file_id:
                await bot.edit_message_caption(
                    chat_id=listing.fair_chat_id,
                    message_id=listing.fair_message_id,
                    caption=html,
                    parse_mode="HTML",
                    reply_markup=markup,
                )
            else:
                await bot.edit_message_text(
                    html,
                    chat_id=listing.fair_chat_id,
                    message_id=listing.fair_message_id,
                    parse_mode="HTML",
                    reply_markup=markup,
                )
            return
        photo = _photo(listing, getattr(settings, "upload_dir", None))
        if photo is not None:
            sent = await bot.send_photo(
                dest.chat_id,
                photo,
                caption=html,
                parse_mode="HTML",
                reply_markup=markup,
                message_thread_id=dest.thread_id,
            )
            if sent.photo:
                listing.fair_file_id = sent.photo[-1].file_id
        else:
            sent = await bot.send_message(
                dest.chat_id,
                html,
                parse_mode="HTML",
                reply_markup=markup,
                message_thread_id=dest.thread_id,
            )
            listing.fair_file_id = None
        listing.fair_chat_id = dest.chat_id
        listing.fair_message_id = sent.message_id
    except (TelegramBadRequest, TelegramForbiddenError) as exc:
        logger.info("fair_card_failed", listing_id=listing.id, error=str(exc))


async def sync_fair_card_from_settings(settings: Any, listing: Listing) -> None:
    if fair_destination(settings) is None:
        return
    bot = create_bot(settings)
    try:
        await sync_fair_card(bot, listing, settings)
    except Exception as exc:
        logger.info("fair_card_failed", listing_id=listing.id, error=str(exc))
    finally:
        await bot.session.close()


async def _delete(bot: Bot, listing: Listing) -> None:
    if not listing.fair_chat_id or not listing.fair_message_id:
        return
    try:
        await bot.delete_message(listing.fair_chat_id, listing.fair_message_id)
    except (TelegramBadRequest, TelegramForbiddenError) as exc:
        logger.info("fair_card_delete_failed", listing_id=listing.id, error=str(exc))
    listing.fair_chat_id = None
    listing.fair_message_id = None
    listing.fair_file_id = None
