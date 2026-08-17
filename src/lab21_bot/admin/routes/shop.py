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
from lab21_bot.data import list_skills, phrase, skill_titles
from lab21_bot.models import ProductKind, ServiceJobStatus, User
from lab21_bot.services.access import Permission, has_permission
from lab21_bot.services.economy import EconomyError
from lab21_bot.services.jobs import JobError, cancel_job, list_active_jobs, mark_job_done
from lab21_bot.services.job_publish import sync_job_board_post
from lab21_bot.services.ranks_catalog import get_ranks_snapshot, rank_by_id
from lab21_bot.services.destinations import shop_destination
from lab21_bot.services.shop_publish import (
    remove_shop_card_from_settings,
    sync_shop_card_from_settings,
)
from lab21_bot.services.store import (
    create_product,
    delete_product,
    list_orders,
    list_products,
    resolve_order,
    update_product_fields,
)
from lab21_bot.services.notify import notify_telegram_user
from lab21_bot.services.uploads import UploadError, save_product_image
from lab21_bot.services.user_messages import message_order_cancelled, message_order_fulfilled

router = APIRouter(tags=["shop"])

KIND_LABELS = {
    "merch": "Мерч",
    "device": "Устройства",
    "service": "Услуга",
}
JOB_STATUS_LABELS = {
    ServiceJobStatus.OPEN.value: "открыт",
    ServiceJobStatus.CLAIMED.value: "на исполнении",
    ServiceJobStatus.REVIEW.value: "подтверждение",
    ServiceJobStatus.DONE.value: "готов",
    ServiceJobStatus.CANCELLED.value: "отменён",
}


def _parse_rank(value: str):
    from lab21_bot.models import CommunityRank

    key = value.strip()
    if rank_by_id(key) is None:
        raise ValueError(f"Неизвестный ранг: {key}")
    try:
        return CommunityRank(key)
    except ValueError:
        return key


def _parse_max_per_user(raw: str) -> int | None:
    value = (raw or "").strip()
    if not value:
        return None
    return int(value)


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
    service_jobs = await list_active_jobs(session) if can_orders else []
    return await render(
        request,
        "shop.html",
        user=user,
        session=session,
        products=products,
        orders=orders,
        service_jobs=service_jobs,
        ranks=[str(item["id"]) for item in get_ranks_snapshot()],
        kinds=list(ProductKind),
        kind_labels=KIND_LABELS,
        skills=list_skills(),
        skill_titles=skill_titles(),
        job_status_labels=JOB_STATUS_LABELS,
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
    skill_ids: Annotated[list[str] | None, Form()] = None,
    respect_reward: Annotated[str, Form()] = "",
    max_per_user: Annotated[str, Form()] = "2",
    image: Annotated[UploadFile | None, File()] = None,
) -> RedirectResponse:
    try:
        stock_value = None if stock.strip().lower() == "inf" else int(stock)
        reward: int | None = None
        if respect_reward.strip():
            reward = int(respect_reward)
        product = await create_product(
            session,
            actor,
            article=article,
            name=name,
            description=description,
            price=price,
            stock=stock_value,
            min_rank=_parse_rank(min_rank),
            kind=ProductKind(kind),
            skill_ids=list(skill_ids or []),
            respect_reward=reward,
            max_per_user=_parse_max_per_user(max_per_user),
        )
        if image is not None and image.filename:
            product.image_path = await save_product_image(
                settings.upload_dir,
                product.id,
                image,
            )
            await session.flush()
        await sync_shop_card_from_settings(settings, product)
        return _shop_redirect("Товар создан")
    except (EconomyError, ValueError, UploadError, OSError) as exc:
        return _shop_redirect(error=str(exc))


@router.post("/shop/products/{product_id}/edit")
async def shop_edit_product(
    product_id: int,
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
    skill_ids: Annotated[list[str] | None, Form()] = None,
    respect_reward: Annotated[str, Form()] = "",
    is_visible: Annotated[str, Form()] = "0",
    max_per_user: Annotated[str, Form()] = "",
    image: Annotated[UploadFile | None, File()] = None,
) -> RedirectResponse:
    try:
        stock_value = None if stock.strip().lower() == "inf" else int(stock)
        reward: int | None = None
        if respect_reward.strip():
            reward = int(respect_reward)
        product = await update_product_fields(
            session,
            actor,
            product_id,
            article=article,
            name=name,
            description=description,
            price=price,
            stock=stock_value,
            min_rank=_parse_rank(min_rank),
            kind=ProductKind(kind),
            skill_ids=list(skill_ids or []),
            respect_reward=reward,
            is_visible=is_visible.lower() in {"1", "true", "yes", "on"},
            max_per_user=_parse_max_per_user(max_per_user),
        )
        if image is not None and image.filename:
            product.image_path = await save_product_image(
                settings.upload_dir,
                product.id,
                image,
            )
            await session.flush()
        await sync_shop_card_from_settings(
            settings,
            product,
            replace_media=bool(image is not None and image.filename),
        )
        return _shop_redirect("Товар обновлён")
    except (EconomyError, ValueError, UploadError, OSError) as exc:
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
        await sync_shop_card_from_settings(settings, product, replace_media=True)
        return _shop_redirect("Фото обновлено")
    except (EconomyError, UploadError, OSError) as exc:
        return _shop_redirect(error=str(exc))


@router.post("/shop/products/{product_id}/publish")
async def shop_publish_product(
    product_id: int,
    session: DbSession,
    settings: SettingsDep,
    actor: RequireManageStore,
) -> RedirectResponse:
    from lab21_bot.models import Product

    product = await session.get(Product, product_id)
    if product is None:
        return _shop_redirect(error="Товар не найден")
    if shop_destination(settings) is None:
        return _shop_redirect(error="Не задан SHOP_THREAD_ID в .env")
    await sync_shop_card_from_settings(settings, product, replace_media=True)
    if not product.shop_message_id:
        return _shop_redirect(
            error="Не удалось отправить карточку. Проверьте SHOP_THREAD_ID и права бота в топике."
        )
    return _shop_redirect("Карточка отправлена в Магазин")


@router.post("/shop/products/{product_id}/unpublish")
async def shop_unpublish_product(
    product_id: int,
    session: DbSession,
    settings: SettingsDep,
    actor: RequireManageStore,
) -> RedirectResponse:
    from lab21_bot.models import Product

    product = await session.get(Product, product_id)
    if product is None:
        return _shop_redirect(error="Товар не найден")
    if not product.shop_message_id:
        return _shop_redirect(error="Карточки в Магазине нет")
    await remove_shop_card_from_settings(settings, product)
    await session.flush()
    return _shop_redirect("Карточка убрана из Магазина")


@router.post("/shop/products/{product_id}/delete")
async def shop_delete_product(
    product_id: int,
    session: DbSession,
    settings: SettingsDep,
    actor: RequireManageStore,
) -> RedirectResponse:
    from lab21_bot.models import Product

    try:
        product = await session.get(Product, product_id)
        if product is None:
            raise EconomyError("Товар не найден")
        await remove_shop_card_from_settings(settings, product)
        await delete_product(session, actor, product_id)
        return _shop_redirect("Товар удалён")
    except EconomyError as exc:
        return _shop_redirect(error=str(exc))


@router.post("/shop/orders/{order_id}/resolve")
async def shop_resolve_order(
    order_id: int,
    session: DbSession,
    settings: SettingsDep,
    actor: RequireModerateOrders,
    approve: Annotated[str, Form()],
) -> RedirectResponse:
    try:
        approved = approve.lower() in {"1", "true", "yes"}
        order, granted_rank = await resolve_order(session, actor, order_id, approve=approved)
        text = (
            message_order_fulfilled(order_id=order.id, new_rank=granted_rank)
            if approved
            else message_order_cancelled(order_id=order.id)
        )
        await notify_telegram_user(
            settings.telegram_bot_token.get_secret_value(),
            order.buyer_id,
            text,
        )
        if not approved and order.product is not None:
            await sync_shop_card_from_settings(settings, order.product)
        label = "Услуга выдана" if approved else "Услуга отменена"
        return _shop_redirect(label)
    except EconomyError as exc:
        return _shop_redirect(error=str(exc))


@router.post("/shop/jobs/{job_id}/done")
async def shop_job_done(
    job_id: int,
    session: DbSession,
    settings: SettingsDep,
    actor: RequireModerateOrders,
) -> RedirectResponse:
    try:
        job = await mark_job_done(session, actor, job_id)
        customer = await session.get(User, job.customer_id)
        from aiogram import Bot

        bot = Bot(settings.telegram_bot_token.get_secret_value())
        try:
            await sync_job_board_post(bot, job, customer, update_text=True)
        finally:
            await bot.session.close()
        if job.assignee_id is not None and job.respect_reward > 0:
            await notify_telegram_user(
                settings.telegram_bot_token.get_secret_value(),
                job.assignee_id,
                phrase(
                    "jobs",
                    "done_respect",
                    amount=job.respect_reward,
                    job_id=job.id,
                ),
            )
        return _shop_redirect("Заказ отмечен выполненным")
    except JobError as exc:
        return _shop_redirect(error=str(exc))


@router.post("/shop/jobs/{job_id}/cancel")
async def shop_job_cancel(
    job_id: int,
    session: DbSession,
    settings: SettingsDep,
    actor: RequireModerateOrders,
) -> RedirectResponse:
    try:
        job = await cancel_job(session, actor, job_id)
        from aiogram import Bot

        bot = Bot(settings.telegram_bot_token.get_secret_value())
        try:
            await sync_job_board_post(bot, job)
        finally:
            await bot.session.close()
        return _shop_redirect("Заказ отменён")
    except JobError as exc:
        return _shop_redirect(error=str(exc))
