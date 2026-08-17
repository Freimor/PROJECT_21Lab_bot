"""Publish product cards to the Магазин forum topic."""

from __future__ import annotations

import re
from dataclasses import dataclass
from html import escape
from pathlib import Path
from typing import Any

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.types import FSInputFile
import structlog

from lab21_bot.data import rank_label, skill_title
from lab21_bot.keyboards import shop_card_keyboard
from lab21_bot.models import Product, ProductKind
from lab21_bot.services.destinations import Destination, shop_destination

logger = structlog.get_logger(__name__)

_QTY_RE = re.compile(r"^\s*(\d+)")

_CAPTION_LIMIT = 1024
_KIND_TITLES = {
    ProductKind.MERCH: "Товар",
    ProductKind.DEVICE: "Устройство",
    ProductKind.SERVICE: "Услуга",
}


def product_is_available(product: Product) -> bool:
    if not product.is_visible:
        return False
    if product.stock is not None and int(product.stock) <= 0:
        return False
    return True


def _kind_title(product: Product) -> str:
    kind = product.kind
    if not isinstance(kind, ProductKind):
        try:
            kind = ProductKind(str(kind))
        except ValueError:
            return "Товар"
    return _KIND_TITLES.get(kind, "Товар")


def format_shop_card_html(product: Product) -> str:
    title = _kind_title(product)
    article = escape(product.article)
    name = escape(product.name)
    desc = escape((product.description or "").strip())
    rank_key = str(getattr(product.min_rank, "value", product.min_rank) or "novice")
    rank = escape(rank_label(rank_key) or rank_key)
    stock = "∞" if product.stock is None else str(product.stock)
    lines = [
        f"<b>{title}</b> · <code>{article}</code>",
        f"<b>{name}</b>",
        "",
        desc,
        "",
        f"Цена: <b>{product.price}</b> 🙏",
        f"Остаток: {stock}",
        f"Мин. ранг: {rank}",
    ]
    if product.kind is ProductKind.SERVICE and product.skill_ids:
        skills = ", ".join(escape(skill_title(sid)) for sid in product.skill_ids)
        lines.append(f"Навыки: {skills or '—'}")
        if product.respect_reward:
            lines.append(f"Исполнителю: <b>{product.respect_reward}</b> ❇")
    if not product.is_visible:
        lines.extend(["", "<i>Снято с витрины</i>"])
    elif product.stock is not None and int(product.stock) <= 0:
        lines.extend(["", "<i>Нет в наличии</i>"])
    html = "\n".join(lines)
    if len(html) <= _CAPTION_LIMIT:
        return html
    overflow = len(html) - _CAPTION_LIMIT + 1
    if len(desc) > overflow:
        desc = desc[: max(0, len(desc) - overflow - 1)] + "…"
        lines[3] = desc
        html = "\n".join(lines)
    return html[:_CAPTION_LIMIT]


def html_user_mention(telegram_id: int, name: str) -> str:
    label = escape((name or "участник").strip() or "участник")
    return f'<a href="tg://user?id={telegram_id}">{label}</a>'


TELEGRAM_ALERT_LIMIT = 200


def telegram_alert_text(text: str) -> str:
    compact = " ".join((text or "").split())
    if len(compact) <= TELEGRAM_ALERT_LIMIT:
        return compact
    return compact[: TELEGRAM_ALERT_LIMIT - 1] + "…"


def parse_shop_quantity(text: str | None) -> int | None:
    match = _QTY_RE.match(text or "")
    if match is None:
        return None
    value = int(match.group(1))
    if value <= 0:
        return None
    return value


@dataclass(frozen=True)
class ShopOrderPreview:
    text: str
    can_confirm: bool


def shop_order_preview(
    *,
    quantity: int,
    unit_price: int,
    balance: int,
    max_per_user: int | None,
    already_qty: int,
    stock: int | None,
) -> ShopOrderPreview:
    if quantity <= 0:
        return ShopOrderPreview("Введите целое число больше нуля", False)
    if max_per_user is not None and already_qty + quantity > max_per_user:
        return ShopOrderPreview(
            f"Нельзя заказать больше {max_per_user}шт на одного человека",
            False,
        )
    if stock is not None and quantity > stock:
        return ShopOrderPreview(f"В наличии только {stock}шт.", False)
    total = unit_price * quantity
    cost = f"Стоимость {quantity}шт. = {total} 🙏."
    if balance >= total:
        return ShopOrderPreview(
            f"{cost} У вас достаточно 🙏 на счету. Заказываем?",
            True,
        )
    return ShopOrderPreview(f"{cost} У вас недостаточно 🙏 на счету", False)


def _photo_input(product: Product, upload_dir: str | Path | None) -> str | FSInputFile | None:
    if product.shop_file_id:
        return product.shop_file_id
    if not product.image_path or not upload_dir:
        return None
    full = Path(upload_dir) / product.image_path
    if not full.is_file():
        return None
    return FSInputFile(full)


async def _delete_shop_message(bot: Bot, product: Product) -> None:
    chat_id = product.shop_chat_id
    message_id = product.shop_message_id
    if not chat_id or not message_id:
        return
    try:
        await bot.delete_message(chat_id, message_id)
    except (TelegramBadRequest, TelegramForbiddenError):
        pass
    product.shop_message_id = None
    product.shop_file_id = None


async def _send_shop_card(
    bot: Bot,
    product: Product,
    dest: Destination,
    html: str,
    markup: Any,
    *,
    upload_dir: str | Path | None,
) -> None:
    thread_kwargs = (
        {"message_thread_id": dest.thread_id} if dest.thread_id is not None else {}
    )
    photo = _photo_input(product, upload_dir)
    try:
        if photo is not None:
            sent = await bot.send_photo(
                dest.chat_id,
                photo,
                caption=html,
                parse_mode="HTML",
                reply_markup=markup,
                **thread_kwargs,
            )
            if sent.photo:
                product.shop_file_id = sent.photo[-1].file_id
        else:
            sent = await bot.send_message(
                dest.chat_id,
                html,
                parse_mode="HTML",
                reply_markup=markup,
                **thread_kwargs,
            )
            product.shop_file_id = None
    except (TelegramBadRequest, TelegramForbiddenError) as exc:
        logger.info(
            "shop_card_send_failed",
            product_id=product.id,
            chat_id=dest.chat_id,
            thread_id=dest.thread_id,
            error=str(exc),
        )
        return
    product.shop_chat_id = dest.chat_id
    product.shop_message_id = sent.message_id


async def sync_shop_card(
    bot: Bot,
    product: Product,
    settings: Any,
    *,
    upload_dir: str | Path | None = None,
    replace_media: bool = False,
) -> None:
    dest = shop_destination(settings)
    if dest is None:
        return
    html = format_shop_card_html(product)
    markup = shop_card_keyboard(product)
    chat_id = product.shop_chat_id
    message_id = product.shop_message_id
    has_existing = bool(chat_id and message_id)
    photo = _photo_input(product, upload_dir)
    wants_photo = photo is not None
    posted_as_photo = bool(product.shop_file_id)

    if replace_media or (has_existing and wants_photo != posted_as_photo):
        await _delete_shop_message(bot, product)
        has_existing = False
        posted_as_photo = False

    if has_existing:
        try:
            if posted_as_photo:
                await bot.edit_message_caption(
                    chat_id=chat_id,
                    message_id=message_id,
                    caption=html,
                    parse_mode="HTML",
                    reply_markup=markup,
                )
            else:
                await bot.edit_message_text(
                    html,
                    chat_id=chat_id,
                    message_id=message_id,
                    parse_mode="HTML",
                    reply_markup=markup,
                )
            return
        except (TelegramBadRequest, TelegramForbiddenError) as exc:
            if "not modified" in str(exc).lower():
                return
            await _delete_shop_message(bot, product)

    await _send_shop_card(bot, product, dest, html, markup, upload_dir=upload_dir)


async def sync_shop_card_from_settings(
    settings: Any,
    product: Product,
    *,
    replace_media: bool = False,
) -> None:
    if shop_destination(settings) is None:
        return
    bot = Bot(settings.telegram_bot_token.get_secret_value())
    try:
        await sync_shop_card(
            bot,
            product,
            settings,
            upload_dir=getattr(settings, "upload_dir", None),
            replace_media=replace_media,
        )
    finally:
        await bot.session.close()


async def remove_shop_card_from_settings(settings: Any, product: Product) -> None:
    bot = Bot(settings.telegram_bot_token.get_secret_value())
    try:
        await _delete_shop_message(bot, product)
    finally:
        await bot.session.close()
