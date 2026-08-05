from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from lab21_bot.models import ContentItem, Order, Product, StaffRole, User
from lab21_bot.services.access import Permission, has_permission

ROLE_LABELS = {
    StaffRole.LORD: "Лорд",
    StaffRole.MAGISTER: "Магистр",
    StaffRole.TECH_PRIEST: "Техножрец",
    StaffRole.WATCHER: "Смотрящий",
}


def onboarding_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Я послушник", callback_data="join:community")],
            [InlineKeyboardButton(text="Я сотрудник", callback_data="join:staff")],
        ]
    )


def main_menu(user: User) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if user.staff_role is None:
        rows.append(
            [
                InlineKeyboardButton(text="Статус", callback_data="menu:balance"),
                InlineKeyboardButton(text="Сделать заказ", callback_data="menu:order"),
            ]
        )
    rows.append(
        [InlineKeyboardButton(text="Предложить материал", callback_data="menu:submit")]
    )
    if user.staff_role is not None:
        rows.append(
            [InlineKeyboardButton(text="Служебное меню", callback_data="menu:staff")]
        )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def staff_menu(user: User) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if has_permission(user, Permission.CREATE_STAFF_CONTENT):
        rows.append([InlineKeyboardButton(text="Создать пост", callback_data="staff:new_post")])
    if has_permission(user, Permission.MODERATE_CONTENT):
        rows.append([InlineKeyboardButton(text="Модерация", callback_data="staff:moderation")])
    if has_permission(user, Permission.MODERATE_ORDERS):
        rows.append([InlineKeyboardButton(text="Заказы", callback_data="staff:orders")])
    if has_permission(user, Permission.MANAGE_STAFF):
        rows.append(
            [InlineKeyboardButton(text="Состав сотрудников", callback_data="staff:list")]
        )
    if has_permission(user, Permission.MANAGE_SETTINGS):
        rows.append([InlineKeyboardButton(text="Настройки", callback_data="staff:settings")])
    if has_permission(user, Permission.MANAGE_SYSTEM):
        rows.append(
            [InlineKeyboardButton(text="Перезагрузка", callback_data="staff:reboot")]
        )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def reboot_confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Перезагрузить", callback_data="reboot:confirm"),
                InlineKeyboardButton(text="Отмена", callback_data="reboot:cancel"),
            ]
        ]
    )


def content_actions(item: ContentItem, *, staff_draft: bool = False) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                text="Опубликовать", callback_data=f"content:publish:{item.id}"
            ),
            InlineKeyboardButton(text="Изменить", callback_data=f"content:edit:{item.id}"),
        ]
    ]
    if staff_draft:
        rows.append(
            [
                InlineKeyboardButton(
                    text="Перегенерировать", callback_data=f"content:regen:{item.id}"
                )
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(text="Уточнить", callback_data=f"content:info:{item.id}"),
            InlineKeyboardButton(text="Отклонить", callback_data=f"content:reject:{item.id}"),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def order_confirm_keyboard(product: Product) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Заказать", callback_data=f"buy:{product.id}"),
                InlineKeyboardButton(text="Отмена", callback_data="order:cancel_draft"),
            ]
        ]
    )


def order_actions(order: Order) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Выдать", callback_data=f"order:approve:{order.id}"
                ),
                InlineKeyboardButton(
                    text="Отменить", callback_data=f"order:cancel:{order.id}"
                ),
            ]
        ]
    )
