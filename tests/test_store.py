from sqlalchemy.ext.asyncio import AsyncSession

from lab21_bot.models import (
    CommunityRank,
    OrderStatus,
    ProductKind,
    StaffRole,
    User,
)
from lab21_bot.services.store import (
    create_product,
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

    await resolve_order(session, watcher, order.id, approve=False)
    assert order.status is OrderStatus.CANCELLED
    assert buyer.balance == 100
    assert product.stock == 2

    await update_product(session, magister, product.id, "visible", "false")
    assert product.is_visible is False


async def test_rank_product_grants_adept_after_moderation(session: AsyncSession) -> None:
    magister = User(telegram_id=10, full_name="Лорд", staff_role=StaffRole.LORD)
    watcher = User(telegram_id=20, full_name="Смотрящий", staff_role=StaffRole.WATCHER)
    buyer = User(telegram_id=30, full_name="Послушник", balance=10)
    session.add_all([magister, watcher, buyer])
    await session.flush()
    initiation = await create_product(
        session,
        magister,
        article="LAB-ADEPT",
        name="Стать Адептом",
        description="Подтверждение вклада в лабораторию",
        price=1,
        stock=None,
        kind=ProductKind.SERVICE,
        grants_rank=CommunityRank.ADEPT,
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
    await resolve_order(session, watcher, order.id, approve=True)

    assert buyer.rank is CommunityRank.ADEPT
    assert adept_only in await visible_products(session, buyer)
