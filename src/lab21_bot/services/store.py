from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from lab21_bot.models import (
    CommunityRank,
    LedgerEntry,
    LedgerType,
    Order,
    OrderStatus,
    Product,
    ProductKind,
    User,
)
from lab21_bot.services.access import Permission, require_permission
from lab21_bot.services.economy import EconomyError

RANK_WEIGHT = {CommunityRank.NOVICE: 0, CommunityRank.ADEPT: 1}


async def visible_products(session: AsyncSession, buyer: User) -> list[Product]:
    products = await session.scalars(
        select(Product).where(Product.is_visible.is_(True)).order_by(Product.id)
    )
    return [
        product
        for product in products
        if RANK_WEIGHT[buyer.rank] >= RANK_WEIGHT[product.min_rank]
        and (product.stock is None or product.stock > 0)
    ]


async def create_product(
    session: AsyncSession,
    actor: User,
    *,
    name: str,
    description: str,
    price: int,
    stock: int | None,
    min_rank: CommunityRank = CommunityRank.NOVICE,
    kind: ProductKind = ProductKind.PHYSICAL,
    grants_rank: CommunityRank | None = None,
) -> Product:
    require_permission(actor, Permission.MANAGE_STORE)
    if price < 0 or stock is not None and stock < 0:
        raise EconomyError("Цена и остаток не могут быть отрицательными")
    product = Product(
        name=name.strip(),
        description=description.strip(),
        price=price,
        stock=stock,
        min_rank=min_rank,
        kind=kind,
        grants_rank=grants_rank,
    )
    session.add(product)
    await session.flush()
    return product


async def purchase(
    session: AsyncSession,
    buyer_id: int,
    product_id: int,
    *,
    quantity: int = 1,
    idempotency_key: str,
) -> Order:
    if quantity <= 0:
        raise EconomyError("Количество должно быть положительным")
    existing = await session.scalar(
        select(Order).where(Order.idempotency_key == idempotency_key)
    )
    if existing:
        return existing

    buyer = await session.scalar(
        select(User).where(User.telegram_id == buyer_id).with_for_update()
    )
    product = await session.scalar(select(Product).where(Product.id == product_id).with_for_update())
    if buyer is None or product is None or not product.is_visible:
        raise EconomyError("Товар недоступен")
    if RANK_WEIGHT[buyer.rank] < RANK_WEIGHT[product.min_rank]:
        raise EconomyError("Для этой награды требуется более высокий ранг")
    if product.stock is not None and product.stock < quantity:
        raise EconomyError("Недостаточный остаток")
    total = product.price * quantity
    if buyer.balance < total:
        raise EconomyError("Недостаточно лабкоинов")

    buyer.balance -= total
    if product.stock is not None:
        product.stock -= quantity
    order = Order(
        idempotency_key=idempotency_key,
        buyer_id=buyer_id,
        product_id=product_id,
        quantity=quantity,
        total_price=total,
    )
    session.add(order)
    await session.flush()
    group = f"order:{idempotency_key}"
    session.add(
        LedgerEntry(
            transaction_group=group,
            idempotency_key=f"purchase:{idempotency_key}",
            initiator_id=buyer_id,
            account_user_id=buyer_id,
            delta=-total,
            balance_after=buyer.balance,
            entry_type=LedgerType.PURCHASE_RESERVE,
            reason=f"Резерв по заказу #{order.id}: {product.name}",
        )
    )
    await session.flush()
    return order


async def resolve_order(
    session: AsyncSession,
    actor: User,
    order_id: int,
    *,
    approve: bool,
) -> Order:
    require_permission(actor, Permission.MODERATE_ORDERS)
    order = await session.scalar(
        select(Order)
        .where(Order.id == order_id)
        .options(selectinload(Order.product))
        .with_for_update()
    )
    if order is None or order.status is not OrderStatus.PENDING:
        raise EconomyError("Заказ уже обработан или не существует")
    buyer = await session.scalar(
        select(User).where(User.telegram_id == order.buyer_id).with_for_update()
    )
    if buyer is None:
        raise EconomyError("Покупатель не найден")

    order.handled_by = actor.telegram_id
    order.handled_at = datetime.now(UTC)
    if approve:
        order.status = OrderStatus.FULFILLED
        if order.product.grants_rank is not None:
            buyer.rank = order.product.grants_rank
    else:
        order.status = OrderStatus.CANCELLED
        buyer.balance += order.total_price
        if order.product.stock is not None:
            order.product.stock += order.quantity
        session.add(
            LedgerEntry(
                transaction_group=str(uuid.uuid4()),
                idempotency_key=f"order-refund:{order.id}",
                initiator_id=actor.telegram_id,
                account_user_id=buyer.telegram_id,
                delta=order.total_price,
                balance_after=buyer.balance,
                entry_type=LedgerType.PURCHASE_REFUND,
                reason=f"Возврат по отменённому заказу #{order.id}",
            )
        )
    await session.flush()
    return order

