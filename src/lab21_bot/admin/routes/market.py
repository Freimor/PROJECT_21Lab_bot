"""Админка ярмарки: карточки лаборатории, склад, выдача, споры."""

from __future__ import annotations

from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse

from lab21_bot.admin.deps import CurrentUser, DbSession, SettingsDep
from lab21_bot.admin.templating import render
from lab21_bot.models import Listing, User
from lab21_bot.services.access import Permission, has_permission
from lab21_bot.services.fair_publish import sync_fair_card_from_settings
from lab21_bot.services.marketplace import (
    CATEGORIES,
    MarketError,
    add_lab_photo,
    add_stock,
    create_lab_listing,
    get_deal_for_staff,
    issue_deal,
    list_admin_listings,
    list_disputes,
    pledge_user_ids,
    refuse_deal,
    remove_listing,
    resolve_dispute,
)
from lab21_bot.services.notify import notify_telegram_user
from lab21_bot.services.uploads import UploadError, save_image

router = APIRouter(tags=["market-admin"])


def _redirect(message: str | None = None, error: str | None = None) -> RedirectResponse:
    if error:
        return RedirectResponse(f"/market?error={quote(error)}", status_code=303)
    return RedirectResponse(f"/market?message={quote(message or 'Готово')}", status_code=303)


def _guard(user: User) -> RedirectResponse | None:
    allowed = (
        has_permission(user, Permission.FAIR_MODERATE)
        or has_permission(user, Permission.FAIR_WAREHOUSE)
        or has_permission(user, Permission.FAIR_DISPUTES)
    )
    if not allowed:
        return RedirectResponse("/", status_code=303)
    return None


@router.get("/market", response_class=HTMLResponse, response_model=None)
async def market_page(
    request: Request,
    session: DbSession,
    user: CurrentUser,
) -> HTMLResponse | RedirectResponse:
    denied = _guard(user)
    if denied is not None:
        return denied
    listings = await list_admin_listings(session)
    disputes = (
        await list_disputes(session)
        if has_permission(user, Permission.FAIR_DISPUTES)
        else []
    )
    return await render(
        request,
        "market.html",
        user=user,
        session=session,
        listings=listings,
        disputes=disputes,
        categories=CATEGORIES,
        can_moderate=has_permission(user, Permission.FAIR_MODERATE),
        can_warehouse=has_permission(user, Permission.FAIR_WAREHOUSE),
        can_disputes=has_permission(user, Permission.FAIR_DISPUTES),
        message=request.query_params.get("message"),
        error=request.query_params.get("error"),
        preview=None,
    )


@router.post("/market/lab")
async def market_lab_create(
    session: DbSession,
    user: CurrentUser,
    settings: SettingsDep,
    title: str = Form(),
    summary: str = Form(),
    description: str = Form(),
    category: str = Form("other"),
    tags: str = Form(""),
    currency: str = Form("grace"),
    price: int = Form(),
    image: Annotated[UploadFile | None, File()] = None,
) -> RedirectResponse:
    if not has_permission(user, Permission.FAIR_MODERATE):
        return _redirect(error="Нет права на витрину")
    try:
        listing = await create_lab_listing(
            session,
            user,
            title=title,
            summary=summary,
            description=description,
            category=category,
            tags=[part.strip() for part in tags.split(",") if part.strip()],
            currency=currency,
            price=price,
        )
        if image is not None and image.filename:
            relative = await save_image(
                settings.upload_dir,
                subdir="market",
                entity_id=listing.id,
                upload=image,
            )
            await add_lab_photo(session, user, listing.id, relative)
    except (MarketError, UploadError, ValueError) as exc:
        return _redirect(error=str(exc))
    return _redirect("Карточка лаборатории создана. Остаток появится после приёмки.")


@router.post("/market/{listing_id}/stock")
async def market_stock(
    listing_id: int,
    session: DbSession,
    user: CurrentUser,
    settings: SettingsDep,
    quantity: int = Form(),
) -> RedirectResponse:
    if not has_permission(user, Permission.FAIR_WAREHOUSE):
        return _redirect(error="Нет права на склад")
    try:
        before = next(
            (item.stock for item in await list_admin_listings(session) if item.id == listing_id),
            0,
        )
        listing = await add_stock(session, user, listing_id, quantity)
        await sync_fair_card_from_settings(settings, listing)
        if (
            str(getattr(listing.kind, "value", listing.kind)) == "collective"
            and before == 0
            and listing.stock > 0
        ):
            token = settings.telegram_bot_token.get_secret_value()
            for user_id in await pledge_user_ids(session, listing.id):
                await notify_telegram_user(
                    token,
                    user_id,
                    (
                        f"Партия «{listing.title}» на складе. "
                        "Открой Маркет и нажми «Купить». Оплата у стойки."
                    ),
                )
    except (MarketError, ValueError) as exc:
        return _redirect(error=str(exc))
    return _redirect("Склад пополнен")


@router.post("/market/{listing_id}/remove")
async def market_remove(
    listing_id: int,
    session: DbSession,
    user: CurrentUser,
    settings: SettingsDep,
    reason: str = Form(),
) -> RedirectResponse:
    if not has_permission(user, Permission.FAIR_MODERATE):
        return _redirect(error="Нет права на витрину")
    try:
        listing = await remove_listing(session, user, listing_id, reason)
        await sync_fair_card_from_settings(settings, listing)
    except MarketError as exc:
        return _redirect(error=str(exc))
    return _redirect("Карточка снята")


@router.post("/market/lookup", response_model=None)
async def market_lookup(
    request: Request,
    session: DbSession,
    user: CurrentUser,
    token: str = Form(),
) -> HTMLResponse | RedirectResponse:
    denied = _guard(user)
    if denied is not None:
        return denied
    preview = await get_deal_for_staff(session, token)
    listings = await list_admin_listings(session)
    disputes = (
        await list_disputes(session)
        if has_permission(user, Permission.FAIR_DISPUTES)
        else []
    )
    error = None if preview is not None else "Заказ с таким кодом не найден"
    return await render(
        request,
        "market.html",
        user=user,
        session=session,
        listings=listings,
        disputes=disputes,
        categories=CATEGORIES,
        can_moderate=has_permission(user, Permission.FAIR_MODERATE),
        can_warehouse=has_permission(user, Permission.FAIR_WAREHOUSE),
        can_disputes=has_permission(user, Permission.FAIR_DISPUTES),
        message=None,
        error=error,
        preview=preview,
        lookup_token=token.strip().lower(),
    )


@router.post("/market/issue")
async def market_issue(
    session: DbSession,
    user: CurrentUser,
    settings: SettingsDep,
    token: str = Form(),
) -> RedirectResponse:
    if not has_permission(user, Permission.FAIR_WAREHOUSE):
        return _redirect(error="Нет права на выдачу")
    try:
        deal = await issue_deal(session, user, token)
        listing = await session.get(Listing, deal.listing_id)
        if listing is not None:
            await sync_fair_card_from_settings(settings, listing)
    except MarketError as exc:
        return _redirect(error=str(exc))
    return _redirect("Выдача подтверждена")


@router.post("/market/refuse")
async def market_refuse(
    session: DbSession,
    user: CurrentUser,
    settings: SettingsDep,
    token: str = Form(),
) -> RedirectResponse:
    if not has_permission(user, Permission.FAIR_WAREHOUSE):
        return _redirect(error="Нет права на выдачу")
    preview = await get_deal_for_staff(session, token)
    if preview is None:
        return _redirect(error="Заказ с таким кодом не найден")
    try:
        await refuse_deal(session, user, preview.id, as_staff=True)
        listing = await session.get(Listing, preview.listing_id)
        if listing is not None:
            await sync_fair_card_from_settings(settings, listing)
    except MarketError as exc:
        return _redirect(error=str(exc))
    return _redirect("Отказ у стойки, резерв вернулся на склад")


@router.post("/market/deals/{deal_id}/resolve")
async def market_resolve(
    deal_id: int,
    session: DbSession,
    user: CurrentUser,
    action: str = Form(),
) -> RedirectResponse:
    if not has_permission(user, Permission.FAIR_DISPUTES):
        return _redirect(error="Нет права на споры")
    try:
        await resolve_dispute(session, user, deal_id, return_stock=action == "return")
    except MarketError as exc:
        return _redirect(error=str(exc))
    if action == "return":
        return _redirect("Спор закрыт, изделие вернулось на склад")
    return _redirect("Спор закрыт без возврата")
