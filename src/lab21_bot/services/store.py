from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from lab21_bot.models import (
    AdminAction,
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


def normalize_article(article: str) -> str:
    return article.strip().upper()


async def visible_products(session: AsyncSession, buyer: User) -> list[Product]:
    products = await session.scalars(
        select(Product).where(Product.is_visible.is_(True)).order_by(Product.article)
    )
    return [
        product
        for product in products
        if RANK_WEIGHT[buyer.rank] >= RANK_WEIGHT[product.min_rank]
        and (product.stock is None or product.stock > 0)
    ]


async def get_product_by_article(session: AsyncSession, article: str) -> Product | None:
    normalized = normalize_article(article)
    if not normalized:
        return None
    return await session.scalar(select(Product).where(Product.article == normalized))


async def list_products(session: AsyncSession) -> list[Product]:
    products = await session.scalars(select(Product).order_by(Product.article))
    return list(products)


async def list_orders(
    session: AsyncSession,
    *,
    status: OrderStatus | None = OrderStatus.PENDING,
    limit: int = 100,
) -> list[Order]:
    query = select(Order).options(selectinload(Order.product)).order_by(Order.created_at.desc())
    if status is not None:
        query = query.where(Order.status == status)
    orders = await session.scalars(query.limit(limit))
    return list(orders)


async def create_product(
    session: AsyncSession,
    actor: User,
    *,
    article: str,
    name: str,
    description: str,
    price: int,
    stock: int | None,
    min_rank: CommunityRank = CommunityRank.NOVICE,
    kind: ProductKind = ProductKind.MERCH,
    grants_rank: CommunityRank | None = None,
    image_path: str | None = None,
) -> Product:
    require_permission(actor, Permission.MANAGE_STORE)
    if price < 0 or (stock is not None and stock < 0):
        raise EconomyError("Цена и остаток не могут быть отрицательными")
    normalized = normalize_article(article)
    if not normalized:
        raise EconomyError("Артикул обязателен")
    existing = await get_product_by_article(session, normalized)
    if existing is not None:
        raise EconomyError(f"Артикул {normalized} уже занят")
    product = Product(
        article=normalized,
        name=name.strip(),
        description=description.strip(),
        price=price,
        stock=stock,
        min_rank=min_rank,
        kind=kind,
        grants_rank=grants_rank,
        image_path=image_path,
    )
    session.add(product)
    await session.flush()
    session.add(
        AdminAction(
            actor_id=actor.telegram_id,
            action="create_product",
            target_id=None,
            details={"product_id": product.id, "article": product.article, "kind": kind.value},
        )
    )
    await session.flush()
    return product


async def update_product(
    session: AsyncSession,
    actor: User,
    product_id: int,
    field: str,
    raw_value: str,
) -> Product:
    require_permission(actor, Permission.MANAGE_STORE)
    product = await session.scalar(
        select(Product).where(Product.id == product_id).with_for_update()
    )
    if product is None:
        raise EconomyError("Награда не найдена")
    value = raw_value.strip()
    if field == "article":
        normalized = normalize_article(value)
        if not normalized:
            raise EconomyError("Артикул обязателен")
        clash = await get_product_by_article(session, normalized)
        if clash is not None and clash.id != product.id:
            raise EconomyError(f"Артикул {normalized} уже занят")
        product.article = normalized
    elif field == "name":
        product.name = value
    elif field == "description":
        product.description = value
    elif field == "price":
        product.price = int(value)
        if product.price < 0:
            raise EconomyError("Цена не может быть отрицательной")
    elif field == "stock":
        product.stock = None if value.lower() == "inf" else int(value)
        if product.stock is not None and product.stock < 0:
            raise EconomyError("Остаток не может быть отрицательным")
    elif field == "visible":
        if value.lower() not in {"true", "false", "1", "0"}:
            raise EconomyError("visible принимает true или false")
        product.is_visible = value.lower() in {"true", "1"}
    elif field == "min_rank":
        product.min_rank = CommunityRank(value)
    elif field == "kind":
        product.kind = ProductKind(value)
    else:
        raise EconomyError(
            "Можно менять: article, name, description, price, stock, visible, min_rank, kind"
        )
    session.add(
        AdminAction(
            actor_id=actor.telegram_id,
            action="update_product",
            details={"product_id": product.id, "field": field, "value": value},
        )
    )
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
    existing = await session.scalar(select(Order).where(Order.idempotency_key == idempotency_key))
    if existing:
        return existing

    buyer = await session.scalar(select(User).where(User.telegram_id == buyer_id).with_for_update())
    product = await session.scalar(
        select(Product).where(Product.id == product_id).with_for_update()
    )
    if buyer is None or product is None or not product.is_visible:
        raise EconomyError("Товар недоступен")
    if buyer.staff_role is not None:
        raise EconomyError("У сотрудников нет благодати")
    if RANK_WEIGHT[buyer.rank] < RANK_WEIGHT[product.min_rank]:
        raise EconomyError("Для этой награды требуется более высокий ранг")
    if product.stock is not None and product.stock < quantity:
        raise EconomyError("Недостаточный остаток")
    total = product.price * quantity
    if buyer.balance < total:
        raise EconomyError("Недостаточно благодати")

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
    session.add(
        AdminAction(
            actor_id=actor.telegram_id,
            action="fulfill_order" if approve else "cancel_order",
            target_id=buyer.telegram_id,
            details={
                "order_id": order.id,
                "product_id": order.product_id,
                "total_price": order.total_price,
            },
        )
    )
    await session.flush()
    return order
