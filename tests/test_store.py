import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from lab21_bot.models import (
    CommunityRank,
    OrderStatus,
    ProductKind,
    StaffRole,
    User,
)
from lab21_bot.services.economy import EconomyError
from lab21_bot.services.store import (
    create_product,
    delete_product,
    purchase,
    resolve_order,
    update_product,
    visible_products,
)


async def test_purchase_reserves_and_cancel_refunds(session: AsyncSession) -> None:
    magister = User(telegram_id=1, full_name="Лорд", staff_role=StaffRole.LORD)
    watcher = User(telegram_id=2, full_name="Смотрящий", staff_role=StaffRole.WATCHER)
    buyer = User(telegram_id=3, full_name="Послушник", balance=100)
    session.add_all([magister, watcher, buyer])
    await session.flush()
    product = await create_product(
        session,
        magister,
        article="LAB-BADGE",
        name="Значок",
        description="Светящийся PCB-art",
        price=25,
        stock=2,
    )

    order = await purchase(session, buyer.telegram_id, product.id, idempotency_key="buy-1")
    assert buyer.balance == 75
    assert product.stock == 1
    assert order.status is OrderStatus.PENDING

    order_resolved, _ = await resolve_order(session, watcher, order.id, approve=False)
    assert order_resolved.status is OrderStatus.CANCELLED
    assert order.status is OrderStatus.CANCELLED
    assert buyer.balance == 100
    assert product.stock == 2

    await update_product(session, magister, product.id, "visible", "false")
    assert product.is_visible is False


async def test_rank_product_grants_adept_after_moderation(session: AsyncSession) -> None:
    magister = User(telegram_id=10, full_name="Лорд", staff_role=StaffRole.LORD)
    watcher = User(telegram_id=20, full_name="Смотрящий", staff_role=StaffRole.WATCHER)
    buyer = User(telegram_id=30, full_name="Послушник", balance=50)
    session.add_all([magister, watcher, buyer])
    await session.flush()
    initiation = await create_product(
        session,
        magister,
        article="LAB-ADEPT",
        name="Стать Адептом",
        description="Подтверждение вклада в лабораторию",
        price=30,
        stock=None,
        kind=ProductKind.SERVICE,
        grants_rank=CommunityRank.ADEPT,
        skill_ids=["docs_pm"],
        respect_reward=3,
    )
    adept_only = await create_product(
        session,
        magister,
        article="LAB-SECRET",
        name="Тайная награда",
        description="Видна Адептам",
        price=5,
        stock=None,
        min_rank=CommunityRank.ADEPT,
    )

    before = await visible_products(session, buyer)
    assert initiation in before
    assert adept_only not in before

    order = await purchase(
        session,
        buyer.telegram_id,
        initiation.id,
        idempotency_key="initiation",
    )
    _, granted = await resolve_order(session, watcher, order.id, approve=True)

    assert granted is CommunityRank.ADEPT
    assert buyer.rank is CommunityRank.ADEPT
    assert adept_only in await visible_products(session, buyer)


def test_shop_card_html_and_keyboard() -> None:
    from lab21_bot.keyboards import shop_card_keyboard
    from lab21_bot.models import Product, ProductKind
    from lab21_bot.services.shop_publish import format_shop_card_html, product_is_available

    product = Product(
        id=3,
        article="LAB-01",
        name="Значок",
        description="PCB-art",
        price=25,
        stock=2,
        kind=ProductKind.MERCH,
        is_visible=True,
        min_rank=CommunityRank.NOVICE,
    )
    html = format_shop_card_html(product)
    assert "Товар" in html
    assert "LAB-01" in html
    assert "Значок" in html
    assert "25" in html and "🙏" in html
    assert product_is_available(product)
    button = shop_card_keyboard(product).inline_keyboard[0][0]
    assert button.text == "Заказать"
    assert button.callback_data == "shop_buy:3"

    product.stock = 0
    assert not product_is_available(product)
    assert "Нет в наличии" in format_shop_card_html(product)
    assert shop_card_keyboard(product).inline_keyboard[0][0].text == "Нет в наличии"

    product.stock = 2
    product.is_visible = False
    assert not product_is_available(product)
    assert shop_card_keyboard(product).inline_keyboard[0][0].text == "Снято с витрины"


def test_shop_order_preview_funds_and_cap() -> None:
    from lab21_bot.keyboards import shop_qty_keyboard
    from lab21_bot.services.shop_publish import (
        parse_shop_quantity,
        shop_order_preview,
        telegram_alert_text,
    )

    assert parse_shop_quantity("5") == 5
    assert parse_shop_quantity("5шт.") == 5
    assert parse_shop_quantity("нет") is None

    enough = shop_order_preview(
        quantity=5,
        unit_price=48,
        balance=240,
        max_per_user=10,
        already_qty=0,
        stock=None,
    )
    assert enough.can_confirm
    assert enough.text == "Стоимость 5шт. = 240 🙏. У вас достаточно 🙏 на счету. Заказываем?"

    poor = shop_order_preview(
        quantity=5,
        unit_price=48,
        balance=100,
        max_per_user=10,
        already_qty=0,
        stock=None,
    )
    assert not poor.can_confirm
    assert poor.text == "Стоимость 5шт. = 240 🙏. У вас недостаточно 🙏 на счету"

    capped = shop_order_preview(
        quantity=3,
        unit_price=48,
        balance=1000,
        max_per_user=2,
        already_qty=0,
        stock=None,
    )
    assert not capped.can_confirm
    assert capped.text == "Нельзя заказать больше 2шт на одного человека"
    assert len(telegram_alert_text(poor.text)) <= 200
    assert len(telegram_alert_text(capped.text)) <= 200
    assert telegram_alert_text("a" * 250).endswith("…")
    assert len(telegram_alert_text("a" * 250)) == 200

    qty_kb = shop_qty_keyboard(3, 1, 42)
    row, actions = qty_kb.inline_keyboard
    assert [btn.text for btn in row] == ["−", "1", "+"]
    assert row[0].callback_data == "shop_qty:dec:3:1:42"
    assert row[2].callback_data == "shop_qty:inc:3:1:42"
    assert actions[0].callback_data == "shop_qty:ok:3:1:42"
    assert actions[1].callback_data == "shop_abort:42"


async def test_purchase_respects_max_per_user(session: AsyncSession) -> None:
    magister = User(telegram_id=41, full_name="Лорд", staff_role=StaffRole.LORD)
    buyer = User(telegram_id=42, full_name="Послушник", balance=500)
    session.add_all([magister, buyer])
    await session.flush()
    product = await create_product(
        session,
        magister,
        article="LAB-CAP",
        name="Значок",
        description="PCB",
        price=10,
        stock=None,
        max_per_user=2,
    )
    first = await purchase(
        session,
        buyer.telegram_id,
        product.id,
        quantity=2,
        idempotency_key="cap-1",
    )
    assert first.quantity == 2
    with pytest.raises(EconomyError, match="больше 2шт"):
        await purchase(
            session,
            buyer.telegram_id,
            product.id,
            quantity=1,
            idempotency_key="cap-2",
        )


def test_service_shop_card_includes_respect() -> None:
    from lab21_bot.models import Product, ProductKind
    from lab21_bot.services.shop_publish import format_shop_card_html

    product = Product(
        id=4,
        article="LAB-SVC",
        name="Пайка",
        description="Модуль",
        price=80,
        stock=None,
        kind=ProductKind.SERVICE,
        is_visible=True,
        skill_ids=["solder_master"],
        respect_reward=5,
        min_rank=CommunityRank.NOVICE,
    )
    html = format_shop_card_html(product)
    assert "Услуга" in html
    assert "80" in html and "🙏" in html
    assert "5" in html and "❇" in html


async def test_delete_product_without_orders(session: AsyncSession) -> None:
    magister = User(telegram_id=51, full_name="Лорд", staff_role=StaffRole.LORD)
    session.add(magister)
    await session.flush()
    product = await create_product(
        session,
        magister,
        article="LAB-DEL",
        name="Значок",
        description="PCB",
        price=10,
        stock=1,
    )
    product_id = product.id
    await delete_product(session, magister, product_id)
    from lab21_bot.models import Product

    assert await session.get(Product, product_id) is None
