from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter
from pydantic import BaseModel, Field

from lab21_bot.data import setting_default
from lab21_bot.miniapp.deps import DbSession, MiniAppUser, SettingsDep, map_service_error
from lab21_bot.miniapp.serializers import content_to_dict, join_application_to_dict, order_to_dict, product_to_dict
from lab21_bot.models import ContentStatus, OrderStatus, ProductKind
from lab21_bot.services.access import Permission, require_permission
from lab21_bot.services.applications import ApplicationError, list_pending_applications, resolve_application
from lab21_bot.services.content import (
    list_moderation_queue,
    moderate_content,
    publish_content_item,
    reject_content,
    update_draft_text,
)
from lab21_bot.services.economy import EconomyError, change_balance
from lab21_bot.services.lifecycle import check_github_updates, request_restart
from lab21_bot.services.settings import SettingError, get_int_setting, set_int_setting
from lab21_bot.services.store import create_product, list_orders, list_products, resolve_order
from lab21_bot.telegram_client import create_bot

router = APIRouter(tags=["miniapp-staff"], prefix="/staff")

StaffUser = Annotated[object, ...]  # placeholder replaced below


@router.get("/dashboard")
async def staff_dashboard(session: DbSession, user: MiniAppUser) -> dict:
    if user.staff_role is None:
        return {"error": "forbidden"}
    pending_apps = await list_pending_applications(session)
    queue = await list_moderation_queue(session, limit=20)
    orders = await list_orders(session, status=OrderStatus.PENDING, limit=20)
    return {
        "pending_applications": len(pending_apps),
        "moderation_queue": len(queue),
        "pending_orders": len(orders),
    }


@router.get("/content/queue")
async def staff_content_queue(session: DbSession, user: MiniAppUser) -> dict:
    require_permission(user, Permission.MODERATE_CONTENT)
    items = await list_moderation_queue(session, limit=50, include_memes=True)
    return {"items": [content_to_dict(item) for item in items]}


class ContentActionBody(BaseModel):
    action: str
    note: str | None = None
    draft_text: str | None = None


@router.post("/content/{item_id}")
async def staff_content_action(
    item_id: int,
    body: ContentActionBody,
    session: DbSession,
    settings: SettingsDep,
    user: MiniAppUser,
) -> dict:
    require_permission(user, Permission.MODERATE_CONTENT)
    async with create_bot(settings) as bot:
        if body.action == "approve":
            item = await moderate_content(
                session,
                user,
                item_id,
                ContentStatus.APPROVED,
                edited_text=body.draft_text,
                note=body.note,
            )
            await publish_content_item(bot, session, settings, item)
        elif body.action == "reject":
            item = await reject_content(session, user, item_id, note=body.note)
        elif body.action == "edit":
            item = await update_draft_text(session, user, item_id, body.draft_text or "")
        else:
            raise map_service_error(RuntimeError("Неизвестное действие"))
    return content_to_dict(item)


@router.get("/orders")
async def staff_orders(session: DbSession, user: MiniAppUser) -> dict:
    require_permission(user, Permission.MODERATE_ORDERS)
    orders = await list_orders(session, status=OrderStatus.PENDING, limit=100)
    return {"orders": [order_to_dict(order) for order in orders]}


class OrderActionBody(BaseModel):
    action: str


@router.post("/orders/{order_id}")
async def staff_order_action(
    order_id: int,
    body: OrderActionBody,
    session: DbSession,
    user: MiniAppUser,
) -> dict:
    require_permission(user, Permission.MODERATE_ORDERS)
    order, _rank = await resolve_order(
        session,
        user,
        order_id,
        approve=body.action == "fulfill",
    )
    return order_to_dict(order)


@router.get("/people/applications")
async def staff_applications(session: DbSession, user: MiniAppUser) -> dict:
    require_permission(user, Permission.MANAGE_STAFF)
    apps = await list_pending_applications(session)
    return {"applications": [join_application_to_dict(app) for app in apps]}


class ApplicationActionBody(BaseModel):
    action: str
    note: str | None = None
    skill_ids: list[str] = Field(default_factory=list)


@router.post("/people/applications/{app_id}")
async def staff_application_action(
    app_id: int,
    body: ApplicationActionBody,
    session: DbSession,
    user: MiniAppUser,
) -> dict:
    require_permission(user, Permission.MANAGE_STAFF)
    try:
        app = await resolve_application(
            session,
            user,
            app_id,
            approve=body.action == "approve",
            note=body.note,
            skill_ids=body.skill_ids or None,
        )
    except ApplicationError as exc:
        raise map_service_error(exc) from exc
    return join_application_to_dict(app)


@router.get("/settings")
async def staff_settings_get(session: DbSession, user: MiniAppUser, settings: SettingsDep) -> dict:
    require_permission(user, Permission.MANAGE_SETTINGS)
    return {
        "content_silence_days": await get_int_setting(
            session, "content_silence_days", settings.content_silence_days
        ),
        "reminder_hour": await get_int_setting(session, "reminder_hour", settings.reminder_hour),
        "transfer_daily_limit": await get_int_setting(
            session, "transfer_daily_limit", settings.transfer_daily_limit
        ),
        "memes_enabled": await get_int_setting(
            session, "memes_enabled", setting_default("memes_enabled")
        ),
        "interview_enabled": await get_int_setting(
            session, "interview_enabled", setting_default("interview_enabled")
        ),
    }


class SettingPatch(BaseModel):
    key: str
    value: int


@router.patch("/settings")
async def staff_settings_patch(body: SettingPatch, session: DbSession, user: MiniAppUser) -> dict:
    require_permission(user, Permission.MANAGE_SETTINGS)
    try:
        await set_int_setting(session, user, body.key, body.value)
    except SettingError as exc:
        raise map_service_error(exc) from exc
    return {"ok": True}


@router.get("/products")
async def staff_products(session: DbSession, user: MiniAppUser) -> dict:
    require_permission(user, Permission.MANAGE_STORE)
    products = await list_products(session)
    return {"products": [product_to_dict(product) for product in products]}


class ProductBody(BaseModel):
    article: str
    name: str
    description: str
    price: int
    kind: ProductKind = ProductKind.MERCH
    stock: int | None = None
    max_per_user: int | None = None
    skill_ids: list[str] = Field(default_factory=list)
    is_visible: bool = True


@router.post("/products")
async def staff_create_product(body: ProductBody, session: DbSession, user: MiniAppUser) -> dict:
    require_permission(user, Permission.MANAGE_STORE)
    product = await create_product(
        session,
        user,
        article=body.article,
        name=body.name,
        description=body.description,
        price=body.price,
        stock=body.stock,
        kind=body.kind,
        max_per_user=body.max_per_user,
        skill_ids=body.skill_ids,
    )
    return product_to_dict(product)


class GrantBody(BaseModel):
    target_id: int
    amount: int
    reason: str


@router.post("/grants")
async def staff_grant(body: GrantBody, session: DbSession, user: MiniAppUser) -> dict:
    require_permission(user, Permission.MANAGE_ECONOMY)
    try:
        await change_balance(session, user, body.target_id, body.amount, body.reason, grant=True)
    except EconomyError as exc:
        raise map_service_error(exc) from exc
    return {"ok": True}


@router.post("/withdraw")
async def staff_withdraw(body: GrantBody, session: DbSession, user: MiniAppUser) -> dict:
    require_permission(user, Permission.MANAGE_ECONOMY)
    try:
        await change_balance(session, user, body.target_id, body.amount, body.reason, grant=False)
    except EconomyError as exc:
        raise map_service_error(exc) from exc
    return {"ok": True}


@router.post("/reboot")
async def staff_reboot(session: DbSession, user: MiniAppUser, settings: SettingsDep) -> dict:
    require_permission(user, Permission.MANAGE_SYSTEM)
    status = await check_github_updates(settings)
    await request_restart(
        session,
        user,
        settings,
        reason="miniapp reboot",
        update_status=status,
    )
    return {"ok": True, "github": status.__dict__}
