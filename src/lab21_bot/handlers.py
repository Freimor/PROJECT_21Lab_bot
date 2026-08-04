from __future__ import annotations

import asyncio
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InputMediaDocument,
    InputMediaPhoto,
    InputMediaVideo,
    Message,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from lab21_bot.config import Settings
from lab21_bot.keyboards import (
    ROLE_LABELS,
    content_actions,
    main_menu,
    order_actions,
    products_keyboard,
    staff_menu,
)
from lab21_bot.llm.client import LLMClient, LLMError
from lab21_bot.models import (
    CommunityRank,
    ContentItem,
    ContentKind,
    ContentStatus,
    Interview,
    Order,
    OrderStatus,
    Product,
    ProductKind,
    StaffRole,
    User,
)
from lab21_bot.services.access import (
    AccessDenied,
    Permission,
    has_permission,
    list_staff,
    register_user,
    require_permission,
    set_staff_role,
)
from lab21_bot.services.content import (
    ContentError,
    create_staff_draft,
    mark_published,
    moderate_content,
    record_channel_post,
    submit_community_content,
)
from lab21_bot.services.economy import EconomyError, change_balance, history, transfer
from lab21_bot.services.settings import SettingError, get_int_setting, set_int_setting
from lab21_bot.services.store import (
    create_product,
    purchase,
    resolve_order,
    update_product,
    visible_products,
)


class StaffPostState(StatesGroup):
    note = State()


class SubmissionState(StatesGroup):
    story = State()
    meme = State()


class EditContentState(StatesGroup):
    text = State()


ROLE_ALIASES = {
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
        elif message.video:
            media.append({"type": "video", "file_id": message.video.file_id})
        elif message.document:
            media.append({"type": "document", "file_id": message.document.file_id})
    return media


async def _publish_item(bot: Bot, channel_id: int, item: ContentItem) -> int:
    text = item.draft_text or item.source_text
    if not item.media:
        sent = await bot.send_message(channel_id, text)
        return sent.message_id
    caption = text if len(text) <= 1024 else None
    if len(item.media) == 1:
        media = item.media[0]
        if media["type"] == "photo":
            sent = await bot.send_photo(channel_id, media["file_id"], caption=caption)
        elif media["type"] == "video":
            sent = await bot.send_video(channel_id, media["file_id"], caption=caption)
        else:
            sent = await bot.send_document(channel_id, media["file_id"], caption=caption)
        if caption is None:
            text_message = await bot.send_message(channel_id, text)
            return text_message.message_id
        return sent.message_id

    telegram_media: list[InputMediaPhoto | InputMediaVideo | InputMediaDocument] = []
    for index, media in enumerate(item.media):
        item_caption = caption if index == 0 else None
        if media["type"] == "photo":
            telegram_media.append(InputMediaPhoto(media=media["file_id"], caption=item_caption))
        elif media["type"] == "video":
            telegram_media.append(InputMediaVideo(media=media["file_id"], caption=item_caption))
        else:
            telegram_media.append(InputMediaDocument(media=media["file_id"], caption=item_caption))
    sent_group = await bot.send_media_group(
        channel_id,
        telegram_media,  # type: ignore[arg-type]
    )
    if caption is None:
        text_message = await bot.send_message(channel_id, text)
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
    albums = AlbumCollector()

    async def current_user(session: AsyncSession, telegram_id: int) -> User:
        user = await session.get(User, telegram_id)
        if user is None:
            raise AccessDenied("Сначала запустите бота командой /start")
        return user

    @router.message(CommandStart())
    async def start(message: Message) -> None:
        if not message.from_user:
            return
        async with factory.begin() as session:
            user = await register_user(
                session,
                message.from_user.id,
                message.from_user.full_name,
                message.from_user.username,
            )
            await message.answer(
                "Связь с машинным контуром установлена.\n"
                "Здесь хранятся лабкоины, награды и истории сообщества.",
                reply_markup=main_menu(user),
            )

    @router.message(Command("menu"))
    async def show_menu(message: Message) -> None:
        if not message.from_user:
            return
        async with factory() as session:
            user = await current_user(session, message.from_user.id)
            await message.answer("Панель управления:", reply_markup=main_menu(user))

    @router.callback_query(F.data == "menu:balance")
    @router.message(Command("balance"))
    async def show_balance(event: Message | CallbackQuery) -> None:
        telegram_user = event.from_user
        if telegram_user is None:
            return
        async with factory() as session:
            user = await current_user(session, telegram_user.id)
            label = "Адепт" if user.rank is CommunityRank.ADEPT else "Послушник"
            text = f"Ранг: {label}\nБаланс: {user.balance} лабкоинов"
        if isinstance(event, CallbackQuery):
            await event.answer()
            if event.message:
                await event.message.answer(text)
        else:
            await event.answer(text)

    @router.message(Command("history"))
    async def show_history(message: Message) -> None:
        if not message.from_user:
            return
        async with factory() as session:
            await current_user(session, message.from_user.id)
            entries = await history(session, message.from_user.id)
            lines = [
                f"{entry.created_at:%d.%m} {entry.delta:+d} — {entry.reason}" for entry in entries
            ]
        await message.answer("\n".join(lines) if lines else "История пока пуста.")

    @router.callback_query(F.data == "menu:shop")
    @router.message(Command("shop"))
    async def show_shop(event: Message | CallbackQuery) -> None:
        if event.from_user is None:
            return
        async with factory() as session:
            user = await current_user(session, event.from_user.id)
            products = await visible_products(session, user)
        text = "Доступные награды:" if products else "Для вашего ранга наград пока нет."
        markup = products_keyboard(products) if products else None
        if isinstance(event, CallbackQuery):
            await event.answer()
            if event.message:
                await event.message.answer(text, reply_markup=markup)
        else:
            await event.answer(text, reply_markup=markup)

    @router.callback_query(F.data.startswith("buy:"))
    async def buy_product(callback: CallbackQuery, bot: Bot) -> None:
        product_id = int(callback.data.split(":")[-1])  # type: ignore[union-attr]
        try:
            async with factory.begin() as session:
                order = await purchase(
                    session,
                    callback.from_user.id,
                    product_id,
                    idempotency_key=f"callback:{callback.id}",
                )
                product = await session.get(Product, product_id)
                assert product is not None
                buyer = await session.get(User, callback.from_user.id)
                assert buyer is not None
            await callback.answer("Заказ создан")
            if callback.message:
                await callback.message.answer(
                    f"Заказ #{order.id} создан. Зарезервировано {order.total_price} 🪙."
                )
            await bot.send_message(
                settings.staff_chat_id,
                f"Новый заказ #{order.id}: {product.name}\n"
                f"Покупатель: {buyer.full_name} ({buyer.telegram_id})",
                reply_markup=order_actions(order),
            )
        except EconomyError as error:
            await callback.answer(str(error), show_alert=True)

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
            await message.answer(f"Передано {amount} лабкоинов.")
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
                f"Проводка выполнена: {entry.delta:+d} 🪙. Баланс: {entry.balance_after}."
            )
        except (ValueError, EconomyError, AccessDenied) as error:
            await message.answer(str(error))

    @router.message(Command("staff"))
    async def staff_command(message: Message) -> None:
        if not message.from_user:
            return
        parts = (message.text or "").split()
        if len(parts) == 1:
            async with factory() as session:
                actor = await current_user(session, message.from_user.id)
                if actor.staff_role is None:
                    raise AccessDenied("Служебное меню недоступно")
                await message.answer("Служебное меню:", reply_markup=staff_menu(actor))
            return
        if len(parts) != 3 or parts[2].lower() not in ROLE_ALIASES:
            await message.answer("Формат: /staff TELEGRAM_ID magister|tech_priest|watcher|none")
            return
        try:
            async with factory.begin() as session:
                actor = await current_user(session, message.from_user.id)
                target = await current_user(session, int(parts[1]))
                await set_staff_role(session, actor, target, ROLE_ALIASES[parts[2].lower()])
            await message.answer("Служебная роль обновлена.")
        except (ValueError, AccessDenied) as error:
            await message.answer(str(error))

    @router.callback_query(F.data == "menu:staff")
    async def staff_menu_callback(callback: CallbackQuery) -> None:
        async with factory() as session:
            actor = await current_user(session, callback.from_user.id)
            if actor.staff_role is None:
                await callback.answer("Нет доступа", show_alert=True)
                return
            await callback.answer()
            if callback.message:
                await callback.message.answer("Служебное меню:", reply_markup=staff_menu(actor))

    @router.callback_query(F.data == "staff:list")
    async def staff_list_callback(callback: CallbackQuery) -> None:
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
            await callback.message.answer("\n".join(lines))

    @router.message(Command("setting"))
    async def setting_command(message: Message) -> None:
        if not message.from_user:
            return
        parts = (message.text or "").split()
        if len(parts) != 3:
            await message.answer(
                "Формат: /setting КЛЮЧ ЗНАЧЕНИЕ\n"
                "Ключи: content_silence_days, reminder_hour, transfer_daily_limit"
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
            await message.answer("Настройка сохранена.")
        except (ValueError, AccessDenied, SettingError) as error:
            await message.answer(str(error))

    @router.callback_query(F.data == "staff:settings")
    async def settings_callback(callback: CallbackQuery) -> None:
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
        await callback.answer()
        if callback.message:
            await callback.message.answer(
                "Настройки:\n"
                f"content_silence_days = {silence_days}\n"
                f"reminder_hour = {reminder_hour}\n"
                f"transfer_daily_limit = {transfer_limit}\n\n"
                "Изменение: /setting КЛЮЧ ЗНАЧЕНИЕ"
            )

    @router.callback_query(F.data.in_({"staff:new_post"}))
    @router.message(Command("post"))
    async def begin_staff_post(event: Message | CallbackQuery, state: FSMContext) -> None:
        if event.from_user is None:
            return
        async with factory() as session:
            actor = await current_user(session, event.from_user.id)
            require_permission(actor, Permission.CREATE_STAFF_CONTENT)
        await state.set_state(StaffPostState.note)
        text = "Пришлите фактическую заметку. Бот превратит её в черновик поста."
        if isinstance(event, CallbackQuery):
            await event.answer()
            if event.message:
                await event.message.answer(text)
        else:
            await event.answer(text)

    @router.message(StaffPostState.note, F.text)
    async def generate_staff_post(message: Message, state: FSMContext) -> None:
        if not message.from_user or not message.text:
            return
        wait = await message.answer("Пробуждаю локальный машинный разум…")
        try:
            generated = await llm.generate_staff_post(message.text)
            async with factory.begin() as session:
                actor = await current_user(session, message.from_user.id)
                item = await create_staff_draft(session, actor, message.text, generated)
            await state.clear()
            await wait.edit_text(generated, reply_markup=content_actions(item, staff_draft=True))
        except (LLMError, AccessDenied) as error:
            await wait.edit_text(str(error))

    @router.callback_query(F.data.startswith("content:regen:"))
    async def regenerate_content(callback: CallbackQuery) -> None:
        item_id = int(callback.data.split(":")[-1])  # type: ignore[union-attr]
        try:
            async with factory() as session:
                actor = await current_user(session, callback.from_user.id)
                require_permission(actor, Permission.CREATE_STAFF_CONTENT)
                item = await session.get(ContentItem, item_id)
                if item is None or item.kind is not ContentKind.STAFF_NOTE:
                    raise ContentError("Черновик не найден")
                source = item.source_text
            generated = await llm.generate_staff_post(source)
            async with factory.begin() as session:
                item = await session.get(ContentItem, item_id, with_for_update=True)
                assert item is not None
                item.draft_text = generated
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
        await state.update_data(item_id=item_id)
        await callback.answer()
        if callback.message:
            await callback.message.answer("Пришлите новую версию текста целиком.")

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
            async with factory() as session:
                actor = await current_user(session, callback.from_user.id)
                item = await session.get(ContentItem, item_id)
                if item is None:
                    raise ContentError("Материал не найден")
                owns_staff_draft = (
                    item.author_id == actor.telegram_id
                    and item.kind is ContentKind.STAFF_NOTE
                    and has_permission(actor, Permission.CREATE_STAFF_CONTENT)
                )
                if not owns_staff_draft:
                    require_permission(actor, Permission.MODERATE_CONTENT)
                if item.status is ContentStatus.PUBLISHED:
                    raise ContentError("Материал уже опубликован")
                session.expunge(item)
            message_id = await _publish_item(bot, settings.main_channel_id, item)
            async with factory.begin() as session:
                await mark_published(session, item_id, message_id, settings.main_channel_id)
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
            await bot.send_message(
                author_id,
                "Смотрящий просит дополнить материал."
                if action == "info"
                else "Материал отклонён. Можно подготовить новую версию.",
            )
            await callback.answer("Статус обновлён")
            if isinstance(callback.message, Message):
                await callback.message.edit_reply_markup(reply_markup=None)
        except (AccessDenied, ContentError) as error:
            await callback.answer(str(error), show_alert=True)

    @router.callback_query(F.data == "menu:submit")
    async def choose_submission(callback: CallbackQuery) -> None:
        from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

        await callback.answer()
        if callback.message:
            await callback.message.answer(
                "Что передаём Смотрящим?",
                reply_markup=InlineKeyboardMarkup(
                    inline_keyboard=[
                        [
                            InlineKeyboardButton(text="История", callback_data="submit:story"),
                            InlineKeyboardButton(text="Мем", callback_data="submit:meme"),
                        ]
                    ]
                ),
            )

    @router.callback_query(F.data.startswith("submit:"))
    async def begin_submission(callback: CallbackQuery, state: FSMContext) -> None:
        kind = callback.data.split(":")[-1]  # type: ignore[union-attr]
        await state.set_state(SubmissionState.story if kind == "story" else SubmissionState.meme)
        await callback.answer()
        if callback.message:
            await callback.message.answer(
                "Пришлите текст, фото, видео, документ или один альбом. "
                "Авторство будет указано автоматически."
            )

    @router.message(SubmissionState.story)
    @router.message(SubmissionState.meme)
    async def receive_submission(message: Message, state: FSMContext, bot: Bot) -> None:
        if not message.from_user:
            return
        messages = await albums.collect(message)
        if messages is None:
            return
        current_state = await state.get_state()
        kind = (
            ContentKind.STORY if current_state == SubmissionState.story.state else ContentKind.MEME
        )
        text = (
            next(
                (item.caption or item.text for item in messages if item.caption or item.text),
                "",
            )
            or ""
        )
        media = _media_from_messages(messages)
        if not text and not media:
            await message.answer("Этот формат не поддерживается.")
            return
        async with factory.begin() as session:
            author = await current_user(session, message.from_user.id)
            item = await submit_community_content(session, author, kind, text, media)
        await state.clear()
        await message.answer(f"Материал #{item.id} передан Смотрящим.")
        await _send_review_item(bot, settings.staff_chat_id, item)

    @router.callback_query(F.data == "staff:moderation")
    async def moderation_queue(callback: CallbackQuery, bot: Bot) -> None:
        async with factory() as session:
            actor = await current_user(session, callback.from_user.id)
            require_permission(actor, Permission.MODERATE_CONTENT)
            items = list(
                await session.scalars(
                    select(ContentItem)
                    .where(ContentItem.status == ContentStatus.MODERATION)
                    .order_by(ContentItem.created_at)
                    .limit(10)
                )
            )
        await callback.answer()
        if not callback.message:
            return
        if not items:
            await callback.message.answer("Очередь модерации пуста.")
        for item in items:
            await _send_review_item(bot, callback.message.chat.id, item)

    @router.callback_query(F.data.regexp(r"^order:(approve|cancel):\d+$"))
    async def order_resolution(callback: CallbackQuery, bot: Bot) -> None:
        _, action, raw_id = callback.data.split(":")  # type: ignore[union-attr]
        try:
            async with factory.begin() as session:
                actor = await current_user(session, callback.from_user.id)
                order = await resolve_order(
                    session, actor, int(raw_id), approve=action == "approve"
                )
                buyer_id = order.buyer_id
            await bot.send_message(
                buyer_id,
                f"Заказ #{order.id} "
                + (
                    "подтверждён."
                    if order.status is OrderStatus.FULFILLED
                    else "отменён, средства возвращены."
                ),
            )
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
                    f"Заказ #{order.id}: {order.product.name}, {order.total_price} 🪙",
                    reply_markup=order_actions(order),
                )

    @router.message(Command("product"))
    async def product_command(message: Message) -> None:
        if not message.from_user:
            return
        raw = (message.text or "").partition(" ")[2]
        parts = [part.strip() for part in raw.split("|")]
        if len(parts) < 4:
            await message.answer(
                "Формат: /product название | описание | цена | остаток/inf | "
                "novice/adept | physical/service/rank | выдаваемый_ранг"
            )
            return
        try:
            price = int(parts[2])
            stock = None if parts[3].lower() == "inf" else int(parts[3])
            min_rank = CommunityRank(parts[4]) if len(parts) > 4 else CommunityRank.NOVICE
            kind = ProductKind(parts[5]) if len(parts) > 5 else ProductKind.PHYSICAL
            grants = CommunityRank(parts[6]) if len(parts) > 6 and parts[6] else None
            async with factory.begin() as session:
                actor = await current_user(session, message.from_user.id)
                product = await create_product(
                    session,
                    actor,
                    name=parts[0],
                    description=parts[1],
                    price=price,
                    stock=stock,
                    min_rank=min_rank,
                    kind=kind,
                    grants_rank=grants,
                )
            await message.answer(f"Награда #{product.id} создана.")
        except (ValueError, EconomyError, AccessDenied) as error:
            await message.answer(str(error))

    @router.callback_query(F.data == "staff:store")
    async def store_admin_help(callback: CallbackQuery) -> None:
        async with factory() as session:
            actor = await current_user(session, callback.from_user.id)
            require_permission(actor, Permission.MANAGE_STORE)
        await callback.answer()
        if callback.message:
            await callback.message.answer(
                "Добавление награды:\n"
                "/product название | описание | цена | остаток/inf | "
                "novice/adept | physical/service/rank | выдаваемый_ранг\n\n"
                "Посвящение: kind=rank, выдаваемый_ранг=adept.\n\n"
                "Изменение: /product_edit ID поле значение\n"
                "Поля: name, description, price, stock, visible, min_rank."
            )

    @router.message(Command("product_edit"))
    async def product_edit_command(message: Message) -> None:
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
            await message.answer(f"Награда #{product.id} обновлена.")
        except (ValueError, EconomyError, AccessDenied) as error:
            await message.answer(str(error))

    @router.channel_post()
    async def channel_activity(message: Message) -> None:
        if message.chat.id != settings.main_channel_id:
            return
        async with factory.begin() as session:
            await record_channel_post(session, settings.main_channel_id, message.message_id)

    @router.message(F.chat.type == "private")
    async def interview_answer(message: Message, bot: Bot) -> None:
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
            if len(answers) < 3:
                question_index = len(answers)
            else:
                interview.state = "generating"
                question_index = -1
        if question_index >= 0:
            from lab21_bot.llm.prompts import INTERVIEW_QUESTIONS

            await message.answer(INTERVIEW_QUESTIONS[question_index])
            return
        note = "\n".join(answers)
        try:
            draft = await llm.generate_staff_post(note)
            async with factory.begin() as session:
                actor = await current_user(session, message.from_user.id)
                item = await create_staff_draft(session, actor, note, draft)
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
            await message.answer(draft, reply_markup=content_actions(item, staff_draft=True))
            await bot.send_message(
                settings.staff_chat_id,
                f"{actor.full_name} завершил интервью. Черновик #{item.id} готов.",
            )
        except (LLMError, AccessDenied) as error:
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
