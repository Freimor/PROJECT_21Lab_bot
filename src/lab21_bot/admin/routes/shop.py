from __future__ import annotations

from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse

from lab21_bot.admin.deps import (
    CurrentUser,
    DbSession,
    RequireManageStore,
    RequireModerateOrders,
    SettingsDep,
)
from lab21_bot.admin.templating import render
from lab21_bot.models import CommunityRank, ProductKind
from lab21_bot.services.access import Permission, has_permission
from lab21_bot.services.economy import EconomyError
from lab21_bot.services.store import create_product, list_orders, list_products, resolve_order, update_product
from lab21_bot.services.uploads import UploadError, save_product_image

router = APIRouter(tags=["shop"])

KIND_LABELS = {
    "merch": "Мерч",
    "device": "Устройства",
    "service": "Услуга",
}


def _shop_redirect(message: str | None = None, error: str | None = None) -> RedirectResponse:
    if error:
        return RedirectResponse(f"/shop?error={quote(error)}", status_code=303)
    return RedirectResponse(f"/shop?message={quote(message or 'Готово')}", status_code=303)


@router.get("/shop", response_class=HTMLResponse)
async def shop_page(
    request: Request,
    session: DbSession,
    user: CurrentUser,
) -> HTMLResponse:
    can_store = has_permission(user, Permission.MANAGE_STORE)
    can_orders = has_permission(user, Permission.MODERATE_ORDERS)
    if not can_store and not can_orders:
        return RedirectResponse("/", status_code=303)
    products = await list_products(session) if can_store or can_orders else []
    orders = await list_orders(session) if can_orders else []
    return render(
        request,
        "shop.html",
        user=user,
        products=products,
        orders=orders,
        ranks=list(CommunityRank),
        kinds=list(ProductKind),
        kind_labels=KIND_LABELS,
        can_store=can_store,
        can_orders=can_orders,
        message=request.query_params.get("message"),
        error=request.query_params.get("error"),
    )


@router.get("/store", response_class=HTMLResponse)
@router.get("/orders", response_class=HTMLResponse)
async def shop_legacy_redirect() -> RedirectResponse:
    return RedirectResponse("/shop", status_code=303)


@router.post("/shop/products/create")
async def shop_create_product(
    session: DbSession,
    settings: SettingsDep,
    actor: RequireManageStore,
    article: Annotated[str, Form()],
    name: Annotated[str, Form()],
    description: Annotated[str, Form()],
    price: Annotated[int, Form()],
    stock: Annotated[str, Form()] = "inf",
    min_rank: Annotated[str, Form()] = "novice",
    kind: Annotated[str, Form()] = "merch",
    image: Annotated[UploadFile | None, File()] = None,
) -> RedirectResponse:
    try:
        stock_value = None if stock.strip().lower() == "inf" else int(stock)
        product = await create_product(
            session,
            actor,
            article=article,
            name=name,
            description=description,
            price=price,
            stock=stock_value,
            min_rank=CommunityRank(min_rank),
            kind=ProductKind(kind),
        )
        if image is not None and image.filename:
            product.image_path = await save_product_image(
                settings.upload_dir,
                product.id,
                image,
            )
            await session.flush()
        return _shop_redirect("Товар создан")
    except (EconomyError, ValueError, UploadError) as exc:
        return _shop_redirect(error=str(exc))


@router.post("/shop/products/{product_id}/edit")
async def shop_edit_product(
    product_id: int,
    session: DbSession,
    actor: RequireManageStore,
    field: Annotated[str, Form()],
    value: Annotated[str, Form()],
) -> RedirectResponse:
    try:
        await update_product(session, actor, product_id, field, value)
        return _shop_redirect("Товар обновлён")
    except EconomyError as exc:
        return _shop_redirect(error=str(exc))


@router.post("/shop/products/{product_id}/image")
async def shop_product_image(
    product_id: int,
    session: DbSession,
    settings: SettingsDep,
    actor: RequireManageStore,
    image: Annotated[UploadFile, File()],
) -> RedirectResponse:
    try:
        from lab21_bot.models import Product

        product = await session.get(Product, product_id)
        if product is None:
            raise EconomyError("Товар не найден")
        product.image_path = await save_product_image(settings.upload_dir, product_id, image)
        await session.flush()
        return _shop_redirect("Фото обновлено")
    except (EconomyError, UploadError) as exc:
        return _shop_redirect(error=str(exc))


@router.post("/shop/orders/{order_id}/resolve")
async def shop_resolve_order(
    order_id: int,
    session: DbSession,
    actor: RequireModerateOrders,
    approve: Annotated[str, Form()],
) -> RedirectResponse:
    try:
        approved = approve.lower() in {"1", "true", "yes"}
        await resolve_order(session, actor, order_id, approve=approved)
        label = "Заказ подтверждён" if approved else "Заказ отменён"
        return _shop_redirect(label)
    except EconomyError as exc:
        return _shop_redirect(error=str(exc))
