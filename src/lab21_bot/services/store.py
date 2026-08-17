from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from lab21_bot.data import rank_level, skills_grace_sum, skills_respect_sum
from lab21_bot.models import (
    AdminAction,
    CommunityRank,
    LedgerEntry,
    LedgerType,
    Order,
    OrderStatus,
    Product,
    ProductKind,
    ServiceJob,
    User,
)
from lab21_bot.services.access import Permission, require_permission
from lab21_bot.services.economy import EconomyError
from lab21_bot.services.jobs import JobError, create_service_job, validate_skill_ids


def rank_weight(rank: CommunityRank | str | None) -> int:
    if rank is None:
        return 0
    return rank_level(str(rank))


def normalize_article(article: str) -> str:
    return article.strip().upper()


def _resolve_product_skills(*, kind: ProductKind, skill_ids: list[str] | None) -> list[str]:
    if kind is not ProductKind.SERVICE:
        return []
    try:
        return validate_skill_ids(skill_ids)
    except JobError as exc:
        raise EconomyError(str(exc)) from exc


async def visible_products(session: AsyncSession, buyer: User) -> list[Product]:
    products = await session.scalars(
        select(Product).where(Product.is_visible.is_(True)).order_by(Product.article)
    )
    return [
        product
        for product in products
        if rank_weight(buyer.rank) >= rank_weight(product.min_rank)
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


async def delete_product(session: AsyncSession, actor: User, product_id: int) -> Product:
    require_permission(actor, Permission.MANAGE_STORE)
    product = await session.scalar(
        select(Product).where(Product.id == product_id).with_for_update()
    )
    if product is None:
        raise EconomyError("Награда не найдена")
    pending = await session.scalar(
        select(func.count())
        .select_from(Order)
        .where(Order.product_id == product_id, Order.status == OrderStatus.PENDING)
    )
    if int(pending or 0) > 0:
        raise EconomyError("Нельзя удалить: есть незакрытые заказы")
    history = await session.scalar(
        select(func.count()).select_from(Order).where(Order.product_id == product_id)
    )
    if int(history or 0) > 0:
        raise EconomyError("Нельзя удалить: есть история заказов. Снимите товар с витрины.")
    await session.execute(
        update(ServiceJob).where(ServiceJob.product_id == product_id).values(product_id=None)
    )
    session.add(
        AdminAction(
            actor_id=actor.telegram_id,
            action="delete_product",
            details={"product_id": product.id, "article": product.article},
        )
    )
    await session.delete(product)
    await session.flush()
    return product


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
    skill_ids: list[str] | None = None,
    respect_reward: int | None = None,
    max_per_user: int | None = 2,
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
    resolved_skills = _resolve_product_skills(kind=kind, skill_ids=skill_ids)
    if kind is ProductKind.SERVICE:
        floor = skills_grace_sum(resolved_skills)
        if price < floor:
            raise EconomyError(f"Минимальная цена услуги: {floor} 🙏")
        if respect_reward is None:
            respect_reward = skills_respect_sum(resolved_skills)
        elif respect_reward < 0:
            raise EconomyError("Респект не может быть отрицательным")
    else:
        respect_reward = None
    if max_per_user is not None and max_per_user < 1:
        raise EconomyError("Лимит на человека должен быть пустым или ≥ 1")
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
        skill_ids=resolved_skills,
        respect_reward=respect_reward,
        max_per_user=max_per_user,
    )
    session.add(product)
    await session.flush()
    session.add(
        AdminAction(
            actor_id=actor.telegram_id,
            action="create_product",
            target_id=None,
            details={
                "product_id": product.id,
                "article": product.article,
                "kind": kind.value,
                "skill_ids": resolved_skills,
                "respect_reward": respect_reward,
            },
        )
    )
    await session.flush()
    return product


async def update_product_fields(
    session: AsyncSession,
    actor: User,
    product_id: int,
    *,
    article: str,
    name: str,
    description: str,
    price: int,
    stock: int | None,
    min_rank: CommunityRank | str,
    kind: ProductKind,
    skill_ids: list[str] | None = None,
    respect_reward: int | None = None,
    is_visible: bool = True,
    max_per_user: int | None = 2,
) -> Product:
    require_permission(actor, Permission.MANAGE_STORE)
    product = await session.scalar(
        select(Product).where(Product.id == product_id).with_for_update()
    )
    if product is None:
        raise EconomyError("Награда не найдена")
    if price < 0 or (stock is not None and stock < 0):
        raise EconomyError("Цена и остаток не могут быть отрицательными")
    normalized = normalize_article(article)
    if not normalized:
        raise EconomyError("Артикул обязателен")
    clash = await get_product_by_article(session, normalized)
    if clash is not None and clash.id != product.id:
        raise EconomyError(f"Артикул {normalized} уже занят")
    from lab21_bot.services.ranks_catalog import rank_by_id

    rank_key = str(getattr(min_rank, "value", min_rank))
    if rank_by_id(rank_key) is None:
        raise EconomyError(f"Неизвестный ранг: {rank_key}")
    resolved_skills = _resolve_product_skills(kind=kind, skill_ids=skill_ids)
    if kind is ProductKind.SERVICE:
        floor = skills_grace_sum(resolved_skills)
        if price < floor:
            raise EconomyError(f"Минимальная цена услуги: {floor} 🙏")
        if respect_reward is None:
            respect_reward = skills_respect_sum(resolved_skills)
        elif respect_reward < 0:
            raise EconomyError("Респект не может быть отрицательным")
    else:
        resolved_skills = []
        respect_reward = None
    product.article = normalized
    product.name = name.strip()
    product.description = description.strip()
    product.price = price
    product.stock = stock
    product.min_rank = min_rank
    product.kind = kind
    product.skill_ids = resolved_skills
    product.respect_reward = respect_reward
    product.is_visible = is_visible
    if max_per_user is not None and max_per_user < 1:
        raise EconomyError("Лимит на человека должен быть пустым или ≥ 1")
    product.max_per_user = max_per_user
    session.add(
        AdminAction(
            actor_id=actor.telegram_id,
            action="update_product",
            details={
                "product_id": product.id,
                "article": product.article,
                "kind": kind.value,
                "skill_ids": resolved_skills,
                "respect_reward": respect_reward,
                "is_visible": is_visible,
            },
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
        if product.kind is ProductKind.SERVICE:
            floor = skills_grace_sum(list(product.skill_ids or []))
            if product.price < floor:
                raise EconomyError(f"Минимальная цена услуги: {floor} 🙏")
    elif field == "stock":
        product.stock = None if value.lower() == "inf" else int(value)
        if product.stock is not None and product.stock < 0:
            raise EconomyError("Остаток не может быть отрицательным")
    elif field == "visible":
        if value.lower() not in {"true", "false", "1", "0"}:
            raise EconomyError("visible принимает true или false")
        product.is_visible = value.lower() in {"true", "1"}
    elif field == "min_rank":
        from lab21_bot.services.ranks_catalog import rank_by_id

        if rank_by_id(value) is None:
            raise EconomyError(f"Неизвестный ранг: {value}")
        try:
            product.min_rank = CommunityRank(value)
        except ValueError:
            product.min_rank = value
    elif field == "kind":
        product.kind = ProductKind(value)
        if product.kind is ProductKind.SERVICE:
            if not product.skill_ids:
                raise EconomyError("Для услуги сначала укажи skill_ids")
        else:
            product.skill_ids = []
            product.respect_reward = None
    elif field == "skill_ids":
        if product.kind is not ProductKind.SERVICE:
            raise EconomyError("Навыки задаются только для услуг")
        ids = [part.strip() for part in value.replace(";", ",").split(",") if part.strip()]
        product.skill_ids = _resolve_product_skills(kind=product.kind, skill_ids=ids)
        floor = skills_grace_sum(product.skill_ids)
        if product.price < floor:
            raise EconomyError(f"Минимальная цена услуги: {floor} 🙏")
        if product.respect_reward is None:
            product.respect_reward = skills_respect_sum(product.skill_ids)
    elif field == "respect_reward":
        if product.kind is not ProductKind.SERVICE:
            raise EconomyError("Респект задаётся только для услуг")
        product.respect_reward = int(value)
        if product.respect_reward < 0:
            raise EconomyError("Респект не может быть отрицательным")
    elif field == "max_per_user":
        if value.lower() in {"", "none", "inf", "-"}:
            product.max_per_user = None
        else:
            product.max_per_user = int(value)
            if product.max_per_user < 1:
                raise EconomyError("Лимит на человека должен быть пустым или ≥ 1")
    else:
        raise EconomyError(
            "Можно менять: article, name, description, price, stock, visible, "
            "min_rank, kind, skill_ids, respect_reward, max_per_user"
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


async def count_user_product_qty(
    session: AsyncSession, buyer_id: int, product_id: int
) -> int:
    total = await session.scalar(
        select(func.coalesce(func.sum(Order.quantity), 0)).where(
            Order.buyer_id == buyer_id,
            Order.product_id == product_id,
            Order.status.in_((OrderStatus.PENDING, OrderStatus.FULFILLED)),
        )
    )
    return int(total or 0)


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
        raise EconomyError("У сотрудников нет 🙏")
    if rank_weight(buyer.rank) < rank_weight(product.min_rank):
        raise EconomyError("Для этой награды требуется более высокий ранг")
    if product.stock is not None and product.stock < quantity:
        raise EconomyError("Недостаточный остаток")
    if product.max_per_user is not None:
        already = await count_user_product_qty(session, buyer_id, product_id)
        if already + quantity > product.max_per_user:
            raise EconomyError(
                f"Нельзя заказать больше {product.max_per_user}шт на одного человека"
            )
    total = product.price * quantity
    if buyer.balance < total:
        raise EconomyError("Недостаточно 🙏")

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
    if product.kind is ProductKind.SERVICE and product.skill_ids:
        reward = product.respect_reward
        if reward is None:
            reward = skills_respect_sum(list(product.skill_ids))
        await create_service_job(
            session,
            customer_id=buyer_id,
            skill_ids=list(product.skill_ids),
            description=f"{product.name}\n{product.description}".strip(),
            price=total,
            respect_reward=reward,
            product_id=product.id,
            order_id=order.id,
            reserve_funds=False,
        )
    await session.flush()
    return order


async def resolve_order(
    session: AsyncSession,
    actor: User,
    order_id: int,
    *,
    approve: bool,
) -> tuple[Order, CommunityRank | None]:
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
    granted_rank: CommunityRank | None = None
    if approve:
        order.status = OrderStatus.FULFILLED
        if order.product.grants_rank is not None:
            previous_rank = buyer.rank
            buyer.rank = order.product.grants_rank
            if buyer.rank is not previous_rank:
                granted_rank = buyer.rank
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
        from lab21_bot.models import ServiceJob, ServiceJobStatus

        linked = await session.scalars(
            select(ServiceJob).where(
                ServiceJob.order_id == order.id,
                ServiceJob.status.in_(
                    [
                        ServiceJobStatus.OPEN,
                        ServiceJobStatus.CLAIMED,
                        ServiceJobStatus.REVIEW,
                    ]
                ),
            )
        )
        for job in linked:
            job.status = ServiceJobStatus.CANCELLED
            job.reserved = False
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
    return order, granted_rank
