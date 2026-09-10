from __future__ import annotations

import uuid

from fastapi import APIRouter
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from lab21_bot.miniapp.deps import ApprovedUser, DbSession, SettingsDep, map_service_error
from lab21_bot.miniapp.serializers import order_to_dict, product_to_dict
from lab21_bot.models import Order, ProductKind
from lab21_bot.services.admin_notify import notify_admin_event
from lab21_bot.services.economy import EconomyError
from lab21_bot.services.job_publish import notify_job_subscribers, publish_service_job
from lab21_bot.services.jobs import get_job_by_order_id
from lab21_bot.services.shop_publish import sync_shop_card
from lab21_bot.services.store import purchase, visible_products
from lab21_bot.telegram_client import create_bot

router = APIRouter(tags=["miniapp-shop"])


class ShopOrderBody(BaseModel):
    product_id: int
    quantity: int = Field(default=1, ge=1, le=99)


@router.get("/shop/products")
async def shop_products(session: DbSession, user: ApprovedUser) -> dict:
    if user.staff_role is not None:
        return {"products": []}
    products = await visible_products(session, user)
    return {"products": [product_to_dict(product) for product in products]}


@router.post("/shop/orders")
async def shop_order(
    body: ShopOrderBody,
    session: DbSession,
    user: ApprovedUser,
    settings: SettingsDep,
) -> dict:
    if user.staff_role is not None:
        raise map_service_error(RuntimeError("Магазин только для участников"), forbidden=True)
    try:
        order = await purchase(
            session,
            user.telegram_id,
            body.product_id,
            quantity=body.quantity,
            idempotency_key=f"miniapp:{uuid.uuid4()}",
        )
    except EconomyError as exc:
        raise map_service_error(exc) from exc

    product = order.product
    service_job = (
        await get_job_by_order_id(session, order.id)
        if product.kind is ProductKind.SERVICE
        else None
    )
    async with create_bot(settings) as bot:
        if service_job is not None:
            await publish_service_job(bot, session, settings, service_job, user)
            await notify_job_subscribers(bot, session, service_job)
        await sync_shop_card(bot, product, settings, upload_dir=settings.upload_dir)
        shop_body = (
            f"[{product.article}] {product.name} × {order.quantity}\n"
            f"Покупатель: {user.full_name} ({user.telegram_id})"
            + (
                "\nУслуга опубликована в топике заказов."
                if product.kind is ProductKind.SERVICE
                else ""
            )
        )
        await notify_admin_event(
            session,
            settings,
            "shop_order",
            title=f"Новый заказ #{order.id}",
            body=shop_body,
            link="/shop",
            bot=bot,
        )
    return order_to_dict(order)


@router.get("/shop/orders")
async def shop_orders(session: DbSession, user: ApprovedUser) -> dict:
    orders = await session.scalars(
        select(Order)
        .where(Order.buyer_id == user.telegram_id)
        .options(selectinload(Order.product))
        .order_by(Order.created_at.desc())
        .limit(100)
    )
    return {"orders": [order_to_dict(order) for order in orders]}
