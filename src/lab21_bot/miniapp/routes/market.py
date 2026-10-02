"""Миниапп ярмарки: витрина, свои карточки и заказы."""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Any

from fastapi import APIRouter, File, UploadFile
from pydantic import BaseModel, Field

from lab21_bot.miniapp.deps import ApprovedUser, DbSession, SettingsDep, map_service_error
from lab21_bot.services.marketplace import (
    CATEGORIES,
    MARKET_INTRO,
    SALES_MODE_TEXT,
    MarketError,
    acknowledge_intro,
    add_photo,
    buy,
    create_member_listing,
    enable_sales_mode,
    get_listing,
    join_listing,
    leave_listing,
    list_deals,
    list_market,
    list_mine,
    open_dispute,
    refuse_deal,
    set_handover,
    update_member_listing,
)
from lab21_bot.services.uploads import UploadError, save_image

router = APIRouter(tags=["miniapp-market"])


class ListingBody(BaseModel):
    title: str
    summary: str
    description: str
    category: str = "other"
    tags: list[str] = Field(default_factory=list)
    currency: str = "grace"
    price: int = Field(gt=0)
    kind: str = "regular"
    batch_threshold: int | None = None
    collection_ends_on: date | None = None


class ListingPatch(BaseModel):
    title: str | None = None
    summary: str | None = None
    description: str | None = None
    category: str | None = None
    tags: list[str] | None = None
    currency: str | None = None
    price: int | None = Field(default=None, gt=0)
    batch_threshold: int | None = None
    collection_ends_on: date | None = None


class BuyBody(BaseModel):
    quantity: int = Field(ge=1, le=99)


class HandoverBody(BaseModel):
    handover_on: date


class DisputeBody(BaseModel):
    text: str


def _today(settings: SettingsDep) -> date:
    return datetime.now(settings.tz).date()


@router.get("/market/meta")
async def market_meta(_user: ApprovedUser) -> dict[str, Any]:
    return {
        "categories": [{"id": key, "title": title} for key, title in CATEGORIES.items()],
        "intro": MARKET_INTRO,
        "sales_mode_text": SALES_MODE_TEXT,
    }


@router.post("/market/intro")
async def market_intro(user: ApprovedUser) -> dict[str, Any]:
    await acknowledge_intro(user)
    return {"market_intro_seen": True}


@router.post("/market/sales-mode")
async def market_sales_mode(user: ApprovedUser) -> dict[str, Any]:
    try:
        await enable_sales_mode(user)
    except MarketError as exc:
        raise map_service_error(exc) from exc
    return {"sales_mode": True}


@router.get("/market/listings")
async def market_listings(
    session: DbSession,
    user: ApprovedUser,
    settings: SettingsDep,
    category: str | None = None,
) -> dict[str, Any]:
    items = await list_market(
        session,
        viewer_id=user.telegram_id,
        today=_today(settings),
        category=category or None,
    )
    return {"listings": items}


@router.get("/market/mine")
async def market_mine(
    session: DbSession,
    user: ApprovedUser,
    settings: SettingsDep,
) -> dict[str, Any]:
    items = await list_mine(session, user, _today(settings))
    return {"listings": items}


@router.get("/market/listings/{listing_id}")
async def market_listing(
    listing_id: int,
    session: DbSession,
    user: ApprovedUser,
    settings: SettingsDep,
) -> dict[str, Any]:
    try:
        return await get_listing(
            session,
            listing_id,
            viewer_id=user.telegram_id,
            today=_today(settings),
        )
    except MarketError as exc:
        raise map_service_error(exc) from exc


@router.post("/market/listings")
async def market_create(
    body: ListingBody,
    session: DbSession,
    user: ApprovedUser,
    settings: SettingsDep,
) -> dict[str, Any]:
    try:
        listing = await create_member_listing(
            session,
            user,
            title=body.title,
            summary=body.summary,
            description=body.description,
            category=body.category,
            tags=body.tags,
            currency=body.currency,
            price=body.price,
            kind=body.kind,
            batch_threshold=body.batch_threshold,
            collection_ends_on=body.collection_ends_on,
            today=_today(settings),
        )
        return await get_listing(
            session,
            listing.id,
            viewer_id=user.telegram_id,
            today=_today(settings),
        )
    except MarketError as exc:
        raise map_service_error(exc) from exc


@router.patch("/market/listings/{listing_id}")
async def market_update(
    listing_id: int,
    body: ListingPatch,
    session: DbSession,
    user: ApprovedUser,
    settings: SettingsDep,
) -> dict[str, Any]:
    try:
        await update_member_listing(
            session,
            user,
            listing_id,
            title=body.title,
            summary=body.summary,
            description=body.description,
            category=body.category,
            tags=body.tags,
            currency=body.currency,
            price=body.price,
            batch_threshold=body.batch_threshold,
            collection_ends_on=body.collection_ends_on,
            today=_today(settings),
        )
        return await get_listing(
            session,
            listing_id,
            viewer_id=user.telegram_id,
            today=_today(settings),
        )
    except MarketError as exc:
        raise map_service_error(exc) from exc


@router.post("/market/listings/{listing_id}/photos")
async def market_photo(
    listing_id: int,
    session: DbSession,
    user: ApprovedUser,
    settings: SettingsDep,
    file: Annotated[UploadFile, File()],
) -> dict[str, Any]:
    try:
        relative = await save_image(
            settings.upload_dir,
            subdir="market",
            entity_id=listing_id,
            upload=file,
        )
        await add_photo(session, user, listing_id, relative)
        return await get_listing(
            session,
            listing_id,
            viewer_id=user.telegram_id,
            today=_today(settings),
        )
    except (MarketError, UploadError) as exc:
        raise map_service_error(exc) from exc


@router.post("/market/listings/{listing_id}/join")
async def market_join(
    listing_id: int,
    session: DbSession,
    user: ApprovedUser,
    settings: SettingsDep,
) -> dict[str, Any]:
    try:
        await join_listing(session, user, listing_id, _today(settings))
        return await get_listing(
            session,
            listing_id,
            viewer_id=user.telegram_id,
            today=_today(settings),
        )
    except MarketError as exc:
        raise map_service_error(exc) from exc


@router.post("/market/listings/{listing_id}/leave")
async def market_leave(
    listing_id: int,
    session: DbSession,
    user: ApprovedUser,
    settings: SettingsDep,
) -> dict[str, Any]:
    try:
        await leave_listing(session, user, listing_id, _today(settings))
        return await get_listing(
            session,
            listing_id,
            viewer_id=user.telegram_id,
            today=_today(settings),
        )
    except MarketError as exc:
        raise map_service_error(exc) from exc


@router.post("/market/listings/{listing_id}/handover")
async def market_handover(
    listing_id: int,
    body: HandoverBody,
    session: DbSession,
    user: ApprovedUser,
    settings: SettingsDep,
) -> dict[str, Any]:
    try:
        await set_handover(session, user, listing_id, body.handover_on, _today(settings))
        return await get_listing(
            session,
            listing_id,
            viewer_id=user.telegram_id,
            today=_today(settings),
        )
    except MarketError as exc:
        raise map_service_error(exc) from exc


@router.post("/market/listings/{listing_id}/buy")
async def market_buy(
    listing_id: int,
    body: BuyBody,
    session: DbSession,
    user: ApprovedUser,
    settings: SettingsDep,
) -> dict[str, Any]:
    try:
        deal = await buy(session, user, listing_id, body.quantity, _today(settings))
    except MarketError as exc:
        raise map_service_error(exc) from exc
    rows = await list_deals(session, user)
    match = next((item for item in rows["purchases"] if item["id"] == deal.id), None)
    return match or {"id": deal.id, "qr_token": deal.qr_token}


@router.get("/market/deals")
async def market_deals(session: DbSession, user: ApprovedUser) -> dict[str, Any]:
    return await list_deals(session, user)


@router.post("/market/deals/{deal_id}/refuse")
async def market_refuse(deal_id: int, session: DbSession, user: ApprovedUser) -> dict[str, Any]:
    try:
        await refuse_deal(session, user, deal_id, as_staff=False)
    except MarketError as exc:
        raise map_service_error(exc) from exc
    return await list_deals(session, user)


@router.post("/market/deals/{deal_id}/dispute")
async def market_dispute(
    deal_id: int,
    body: DisputeBody,
    session: DbSession,
    user: ApprovedUser,
) -> dict[str, Any]:
    try:
        await open_dispute(session, user, deal_id, body.text)
    except MarketError as exc:
        raise map_service_error(exc) from exc
    return await list_deals(session, user)
