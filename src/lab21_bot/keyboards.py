from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from lab21_bot.models import ContentItem, Order, Product, StaffRole, User

ROLE_LABELS = {
    StaffRole.MAGISTER: "Магистр",
    StaffRole.TECH_PRIEST: "Техножрец",
    StaffRole.WATCHER: "Смотрящий",
}


def main_menu(user: User) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(text="🪙 Баланс", callback_data="menu:balance"),
            InlineKeyboardButton(text="🛍 Витрина", callback_data="menu:shop"),
        ],
        [InlineKeyboardButton(text="📨 Предложить материал", callback_data="menu:submit")],
    ]
    if user.staff_role is not None:
        rows.append([InlineKeyboardButton(text="⚙️ Служебное меню", callback_data="menu:staff")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def staff_menu(user: User) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text="✍️ Создать пост", callback_data="staff:new_post")],
        [InlineKeyboardButton(text="📥 Модерация", callback_data="staff:moderation")],
        [InlineKeyboardButton(text="📦 Заказы", callback_data="staff:orders")],
    ]
    if user.staff_role is StaffRole.MAGISTER:
        rows.extend(
            [
                [InlineKeyboardButton(text="👥 Состав сотрудников", callback_data="staff:list")],
                [InlineKeyboardButton(text="🏪 Управление витриной", callback_data="staff:store")],
                [InlineKeyboardButton(text="🛠 Настройки", callback_data="staff:settings")],
                [InlineKeyboardButton(text="🔄 Перезагрузка", callback_data="staff:reboot")],
            ]
        )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def reboot_confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Перезагрузить", callback_data="reboot:confirm"),
                InlineKeyboardButton(text="❌ Отмена", callback_data="reboot:cancel"),
            ]
        ]
    )


def content_actions(item: ContentItem, *, staff_draft: bool = False) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                text="✅ Опубликовать", callback_data=f"content:publish:{item.id}"
            ),
            InlineKeyboardButton(text="✏️ Изменить", callback_data=f"content:edit:{item.id}"),
        ]
    ]
    if staff_draft:
        rows.append(
            [
                InlineKeyboardButton(
                    text="🔄 Перегенерировать", callback_data=f"content:regen:{item.id}"
                )
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(text="❓ Уточнить", callback_data=f"content:info:{item.id}"),
            InlineKeyboardButton(text="❌ Отклонить", callback_data=f"content:reject:{item.id}"),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def products_keyboard(products: list[Product]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"{product.name} — {product.price} 🪙",
                    callback_data=f"buy:{product.id}",
                )
            ]
            for product in products
        ]
    )


def order_actions(order: Order) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Выдано", callback_data=f"order:approve:{order.id}"),
                InlineKeyboardButton(text="↩️ Отмена", callback_data=f"order:cancel:{order.id}"),
            ]
        ]
    )
