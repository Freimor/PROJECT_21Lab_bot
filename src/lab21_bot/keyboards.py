from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo

from lab21_bot.config import Settings, get_settings
from lab21_bot.data import list_skills, role_labels
from lab21_bot.models import (
    ContentItem,
    ContentKind,
    Order,
    Product,
    ServiceJobStatus,
    StaffRole,
    User,
)
from lab21_bot.services.access import Permission, has_permission

_ROLE_LABELS = role_labels()
ROLE_LABELS = {role: _ROLE_LABELS[role.value] for role in StaffRole}


def start_keyboard(settings: Settings | None = None) -> InlineKeyboardMarkup:
    settings = settings or get_settings()
    base = settings.miniapp_base_url.rstrip("/")
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Открыть Lab21", web_app=WebAppInfo(url=base))],
            [InlineKeyboardButton(text="FAQ", web_app=WebAppInfo(url=f"{base}#/faq"))],
        ]
    )


def miniapp_button(text: str, fragment: str = "", settings: Settings | None = None) -> InlineKeyboardButton:
    settings = settings or get_settings()
    base = settings.miniapp_base_url.rstrip("/")
    fragment = fragment.lstrip("#/")
    url = f"{base}#/{fragment}" if fragment else base
    return InlineKeyboardButton(text=text, web_app=WebAppInfo(url=url))


def onboarding_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Я послушник", callback_data="join:community")],
            [InlineKeyboardButton(text="Я сотрудник", callback_data="join:staff")],
        ]
    )


def skill_toggle_keyboard(
    selected: list[str],
    *,
    prefix: str,
    done_data: str,
    back_data: str | None = None,
    multi: bool = True,
    show_prices: bool = False,
) -> InlineKeyboardMarkup:
    selected_set = set(selected)
    rows: list[list[InlineKeyboardButton]] = []
    for item in list_skills():
        skill_id = str(item["id"])
        title = str(item.get("title") or skill_id)
        mark = "✓ " if skill_id in selected_set else ""
        label = f"{mark}{title}"
        if show_prices:
            price = int(item.get("grace_price") or 0)
            label = f"{mark}{title} — {price}"
            if len(label) > 64:
                keep = 64 - len(f"{mark}… — {price}")
                label = f"{mark}{title[: max(1, keep)]}… — {price}"
        elif len(label) > 64:
            label = label[:61] + "…"
        rows.append(
            [
                InlineKeyboardButton(
                    text=label,
                    callback_data=f"{prefix}:{skill_id}",
                )
            ]
        )
    if multi:
        rows.append([InlineKeyboardButton(text="Готово", callback_data=done_data)])
    if back_data:
        rows.append([InlineKeyboardButton(text="← Назад", callback_data=back_data)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def skill_board_keyboard() -> InlineKeyboardMarkup:
    from lab21_bot.services.skills_board import skill_board_choices

    rows: list[list[InlineKeyboardButton]] = []
    for skill_id, title in skill_board_choices():
        rows.append(
            [InlineKeyboardButton(text=title, callback_data=f"skills_board:{skill_id}")]
        )
    rows.append([InlineKeyboardButton(text="← Назад", callback_data="menu:home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def add_skill_keyboard(owned: list[str] | None = None) -> InlineKeyboardMarkup:
    owned_set = set(owned or [])
    rows: list[list[InlineKeyboardButton]] = []
    for item in list_skills():
        skill_id = str(item["id"])
        if skill_id in owned_set:
            continue
        title = str(item.get("title") or skill_id)
        suffix = " (проверка)" if item.get("requires_validation") else ""
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"{title}{suffix}",
                    callback_data=f"add_skill:{skill_id}",
                )
            ]
        )
    if not rows:
        rows.append(
            [InlineKeyboardButton(text="Все навыки уже есть", callback_data="menu:profile")]
        )
    rows.append([InlineKeyboardButton(text="← Назад", callback_data="menu:profile")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def profile_skills_keyboard(owned: list[str] | None = None) -> InlineKeyboardMarkup:
    """Toggle skills: ✓ = already owned (tap to remove), else tap to add."""
    owned_set = set(owned or [])
    rows: list[list[InlineKeyboardButton]] = []
    for item in list_skills():
        skill_id = str(item["id"])
        title = str(item.get("title") or skill_id)
        if skill_id in owned_set:
            label = f"✓ {title}"
        else:
            suffix = " (проверка)" if item.get("requires_validation") else ""
            label = f"{title}{suffix}"
        if len(label) > 64:
            label = label[:61] + "…"
        rows.append(
            [
                InlineKeyboardButton(
                    text=label,
                    callback_data=f"profile_skill:{skill_id}",
                )
            ]
        )
    rows.append([InlineKeyboardButton(text="← Назад", callback_data="menu:profile")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def profile_menu_keyboard(*, open_to_jobs: bool) -> InlineKeyboardMarkup:
    open_label = (
        "Не принимаю заказы"
        if open_to_jobs
        else "Открыт к новым заказам"
    )
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Изменить о себе", callback_data="profile:edit_bio")],
            [InlineKeyboardButton(text="Изменить навыки", callback_data="profile:edit_skills")],
            [InlineKeyboardButton(text=open_label, callback_data="profile:toggle_jobs")],
            [InlineKeyboardButton(text="← Назад", callback_data="menu:home")],
        ]
    )


def job_notify_keyboard(*, enabled: bool) -> InlineKeyboardMarkup:
    label = "Выключить уведомления о заказах" if enabled else "Включить уведомления о заказах"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=label, callback_data="jobs:notify_toggle")],
            [InlineKeyboardButton(text="← Назад", callback_data="menu:profile")],
        ]
    )


def quest_card_keyboard(quest_id: int, *, joined: bool = False) -> InlineKeyboardMarkup:
    if joined:
        text, data = "Отписаться", f"quest_leave:{quest_id}"
    else:
        text, data = "Участвовать", f"quest_join:{quest_id}"
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=text, callback_data=data)]]
    )


def my_quests_keyboard(quests: list) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for quest in quests:
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"Отписаться #{quest.number}",
                    callback_data=f"quest_leave:{quest.id}",
                )
            ]
        )
    rows.append([InlineKeyboardButton(text="← Назад", callback_data="menu:home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def order_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Заказать услугу", callback_data="order:service")],
            [InlineKeyboardButton(text="← Назад", callback_data="order:cancel_draft")],
        ]
    )


def my_jobs_keyboard(jobs: list) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for job in jobs:
        preview = (job.description or "").strip().replace("\n", " ")
        if len(preview) > 28:
            preview = preview[:27] + "…"
        label = f"#{job.id} · {preview}" if preview else f"Заказ #{job.id}"
        if len(label) > 64:
            label = label[:61] + "…"
        rows.append(
            [
                InlineKeyboardButton(
                    text=label,
                    callback_data=f"job_done:{job.id}",
                )
            ]
        )
    rows.append([InlineKeyboardButton(text="← Назад", callback_data="menu:home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def job_board_keyboard(job_id: int, status: ServiceJobStatus | str) -> InlineKeyboardMarkup:
    value = status.value if isinstance(status, ServiceJobStatus) else str(status)
    if value == ServiceJobStatus.OPEN.value:
        text, data = "Взять заказ", f"job_claim:{job_id}"
    elif value in {ServiceJobStatus.CLAIMED.value, ServiceJobStatus.REVIEW.value}:
        text, data = "Заказ в работе", f"job_board:busy:{job_id}"
    elif value == ServiceJobStatus.DONE.value:
        text, data = "Заказ выполнен", f"job_board:done:{job_id}"
    else:
        text, data = "Заказ отменён", f"job_board:cancelled:{job_id}"
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=text, callback_data=data)]]
    )


def shop_card_keyboard(product: Product, settings: Settings | None = None) -> InlineKeyboardMarkup:
    available = product.is_visible and (product.stock is None or int(product.stock) > 0)
    if available:
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [miniapp_button("Открыть в приложении", f"shop", settings)],
            ]
        )
    text = "Снято с витрины" if not product.is_visible else "Нет в наличии"
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=text, callback_data=f"shop_soldout:{product.id}")]]
    )


def job_result_review_keyboard(job_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Подтвердить",
                    callback_data=f"job_review:ok:{job_id}",
                ),
                InlineKeyboardButton(
                    text="Не подтверждать",
                    callback_data=f"job_review:no:{job_id}",
                ),
            ]
        ]
    )


def main_menu(user: User) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if user.staff_role is None:
        rows.append(
            [InlineKeyboardButton(text="Заказать услугу", callback_data="menu:order")]
        )
        rows.append(
            [InlineKeyboardButton(text="Профиль", callback_data="menu:profile")]
        )
        rows.append(
            [InlineKeyboardButton(text="Кто умеет", callback_data="menu:skills")]
        )
        rows.append(
            [InlineKeyboardButton(text="Приклониться", callback_data="menu:ritual")]
        )
        rows.append(
            [InlineKeyboardButton(text="Мои квесты", callback_data="menu:my_quests")]
        )
        rows.append(
            [InlineKeyboardButton(text="Мои заказы", callback_data="menu:my_jobs")]
        )
    rows.append(
        [InlineKeyboardButton(text="Предложить материал", callback_data="menu:submit")]
    )
    if user.staff_role is not None:
        rows.append(
            [InlineKeyboardButton(text="Служебное меню", callback_data="menu:staff")]
        )
    rows.append([InlineKeyboardButton(text="Инструкция", callback_data="menu:help")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def staff_menu(user: User) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if has_permission(user, Permission.CREATE_STAFF_CONTENT):
        rows.append([InlineKeyboardButton(text="Создать пост", callback_data="staff:new_post")])
    if has_permission(user, Permission.MODERATE_CONTENT):
        rows.append(
            [InlineKeyboardButton(text="Очередь публикаций", callback_data="staff:moderation")]
        )
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
    rows.append([InlineKeyboardButton(text="← Назад", callback_data="menu:home")])
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
    if item.kind in {ContentKind.STORY, ContentKind.IMPORTANT} and not item.llm_processed:
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="Одобрить → LLM",
                        callback_data=f"content:regen:{item.id}",
                    ),
                    InlineKeyboardButton(
                        text="Отклонить", callback_data=f"content:reject:{item.id}"
                    ),
                ]
            ]
        )
    rows = [
        [
            InlineKeyboardButton(
                text="Опубликовать", callback_data=f"content:publish:{item.id}"
            ),
            InlineKeyboardButton(text="Изменить", callback_data=f"content:edit:{item.id}"),
        ]
    ]
    if staff_draft or item.kind in {ContentKind.STORY, ContentKind.IMPORTANT}:
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


def shop_qty_keyboard(
    product_id: int, quantity: int, buyer_id: int
) -> InlineKeyboardMarkup:
    qty = max(1, int(quantity))
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="−",
                    callback_data=f"shop_qty:dec:{product_id}:{qty}:{buyer_id}",
                ),
                InlineKeyboardButton(
                    text=str(qty),
                    callback_data=f"shop_qty:nop:{product_id}:{qty}:{buyer_id}",
                ),
                InlineKeyboardButton(
                    text="+",
                    callback_data=f"shop_qty:inc:{product_id}:{qty}:{buyer_id}",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="Заказываем",
                    callback_data=f"shop_qty:ok:{product_id}:{qty}:{buyer_id}",
                ),
                InlineKeyboardButton(
                    text="Отмена",
                    callback_data=f"shop_abort:{buyer_id}",
                ),
            ],
        ]
    )


def shop_confirm_keyboard(
    product_id: int, quantity: int, buyer_id: int
) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Заказываем",
                    callback_data=f"shop_ok:{product_id}:{quantity}:{buyer_id}",
                ),
                InlineKeyboardButton(
                    text="Отмена",
                    callback_data=f"shop_abort:{buyer_id}",
                ),
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


def back_keyboard(callback_data: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="← Назад", callback_data=callback_data)]]
    )


def with_back(
    rows: list[list[InlineKeyboardButton]],
    back_to: str,
) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[*rows, [InlineKeyboardButton(text="← Назад", callback_data=back_to)]]
    )


def cancel_writing_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Да", callback_data="flow:cancel_yes"),
                InlineKeyboardButton(text="Нет", callback_data="flow:cancel_no"),
            ]
        ]
    )
