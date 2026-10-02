"""Ярмарка изделий: карточки, склад, коллективный набор и выдача."""

from __future__ import annotations

import secrets
import uuid
from datetime import UTC, date, datetime
from typing import cast

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from lab21_bot.models import (
    CollectionPhase,
    DealStatus,
    LedgerEntry,
    LedgerType,
    Listing,
    ListingCurrency,
    ListingKind,
    ListingPledge,
    ListingStatus,
    MarketDeal,
    User,
)
from lab21_bot.services.access import Permission, require_permission

CATEGORIES: dict[str, str] = {
    "boards": "Платы",
    "cases": "Корпуса",
    "modules": "Модули",
    "kits": "Наборы",
    "other": "Другое",
}

MARKET_INTRO = (
    "Рубли на карточке можно поставить только в режиме самозанятости. "
    "Изделие должно быть своё, перепродавать купленное нельзя. "
    "Чек выдаёт автор. 21Lab хранит изделие и выдаёт его на пункте выдачи. "
    "Покупатель платит автору у стойки, предоплаты нет. "
    "Продавцы и покупатели — одобренные участники от 18 лет."
)

SALES_MODE_TEXT = (
    "Режим самозанятости (НПД, «Мой налог»): налог 4% с физлица и 6% с юрлица или ИП "
    "платит автор, лимит 2,4 млн ₽ в год, чек автор формирует сам в момент оплаты. "
    "Площадка деньги не принимает и чек не выпускает. "
    "Включая режим, ты подтверждаешь, что тебе есть 18 лет и ты состоишь на НПД."
)

GRACE_RESPECT = 1
MAX_PHOTOS = 5
MAX_TAGS = 8


class MarketError(RuntimeError):
    pass


def available(listing: Listing) -> int:
    return max(0, int(listing.stock) - int(listing.reserved))


def is_buyable(listing: Listing) -> bool:
    if listing.status is not ListingStatus.ACTIVE and str(listing.status) != ListingStatus.ACTIVE:
        return False
    if available(listing) <= 0:
        return False
    kind = _kind(listing)
    phase = _phase(listing)
    if kind is ListingKind.COLLECTIVE:
        return phase is CollectionPhase.READY
    return True


def is_joinable(listing: Listing, today: date) -> bool:
    if _kind(listing) is not ListingKind.COLLECTIVE:
        return False
    if _status(listing) is not ListingStatus.ACTIVE:
        return False
    if _phase(listing) is not CollectionPhase.OPEN:
        return False
    ends = listing.collection_ends_on
    return ends is not None and today <= ends


def price_label(listing: Listing) -> str:
    mark = "₽" if _currency(listing) is ListingCurrency.RUB else "🙏"
    return f"{listing.price} {mark}"


def author_name(listing: Listing) -> str:
    if listing.seller_id is None:
        return "21Lab"
    seller = listing.seller
    if seller is None:
        return "участник"
    return seller.full_name


def listing_dict(
    listing: Listing,
    *,
    pledge_count: int = 0,
    joined: bool = False,
    today: date | None = None,
) -> dict[str, object]:
    kind = _kind(listing)
    phase = _phase(listing)
    currency = _currency(listing)
    category = listing.category if listing.category in CATEGORIES else "other"
    return {
        "id": listing.id,
        "title": listing.title,
        "category": category,
        "category_label": CATEGORIES[category],
        "tags": list(listing.tags or []),
        "summary": listing.summary,
        "description": listing.description,
        "photos": [f"/uploads/{path}" for path in (listing.photos or [])],
        "kind": kind.value,
        "currency": currency.value,
        "price": listing.price,
        "price_label": price_label(listing),
        "stock": listing.stock,
        "available": available(listing),
        "author": author_name(listing),
        "is_lab": listing.seller_id is None,
        "seller_id": listing.seller_id,
        "status": _status(listing).value,
        "phase": phase.value,
        "batch_threshold": listing.batch_threshold,
        "collection_ends_on": _iso(listing.collection_ends_on),
        "handover_on": _iso(listing.handover_on),
        "pledge_count": pledge_count,
        "joined": joined,
        "buyable": is_buyable(listing),
        "joinable": is_joinable(listing, today) if today is not None else False,
        "created_at": listing.created_at.isoformat() if listing.created_at else None,
        "removal_reason": listing.removal_reason,
    }


def deal_dict(deal: MarketDeal, *, title: str, qr_svg: str | None = None) -> dict[str, object]:
    currency = _currency_value(deal.currency)
    mark = "₽" if currency is ListingCurrency.RUB else "🙏"
    status = deal.status.value if isinstance(deal.status, DealStatus) else str(deal.status)
    return {
        "id": deal.id,
        "listing_id": deal.listing_id,
        "title": title,
        "buyer_id": deal.buyer_id,
        "quantity": deal.quantity,
        "unit_price": deal.unit_price,
        "total": deal.unit_price * deal.quantity,
        "currency": currency.value,
        "price_label": f"{deal.unit_price * deal.quantity} {mark}",
        "status": status,
        "qr_token": deal.qr_token if status == DealStatus.RESERVED.value else None,
        "qr_svg": qr_svg if status == DealStatus.RESERVED.value else None,
        "dispute_text": deal.dispute_text,
        "created_at": deal.created_at.isoformat() if deal.created_at else None,
        "issued_at": deal.issued_at.isoformat() if deal.issued_at else None,
    }


def qr_svg(payload: str) -> str | None:
    try:
        import segno  # type: ignore[import-not-found]
    except ImportError:
        return None
    rendered = segno.make(payload, error="m").svg_inline(scale=4)
    return cast(str, rendered)


async def acknowledge_intro(user: User) -> None:
    user.market_intro_seen = True


async def enable_sales_mode(user: User) -> None:
    if user.staff_role is not None:
        raise MarketError("Режим продаж включает участник, не сотрудник")
    if not user.is_approved:
        raise MarketError("Сначала нужно одобрение заявки")
    user.sales_mode = True


async def settle_collections(session: AsyncSession, today: date) -> None:
    rows = list(
        await session.scalars(
            select(Listing).where(
                Listing.kind == ListingKind.COLLECTIVE,
                Listing.collection_phase == CollectionPhase.OPEN,
                Listing.status == ListingStatus.ACTIVE,
                Listing.collection_ends_on.is_not(None),
                Listing.collection_ends_on < today,
            )
        )
    )
    for listing in rows:
        count = await _pledge_count(session, listing.id)
        threshold = int(listing.batch_threshold or 0)
        if count >= threshold:
            listing.collection_phase = CollectionPhase.READY
        else:
            listing.collection_phase = CollectionPhase.FAILED
            listing.status = ListingStatus.CLOSED


async def list_market(
    session: AsyncSession,
    *,
    viewer_id: int,
    today: date,
    category: str | None = None,
) -> list[dict[str, object]]:
    await settle_collections(session, today)
    stmt = (
        select(Listing)
        .where(Listing.status == ListingStatus.ACTIVE)
        .options(selectinload(Listing.seller))
        .order_by(Listing.created_at.desc())
    )
    if category:
        stmt = stmt.where(Listing.category == category)
    listings = list(await session.scalars(stmt))
    return await _pack(session, listings, viewer_id=viewer_id, today=today)


async def list_mine(
    session: AsyncSession,
    seller: User,
    today: date,
) -> list[dict[str, object]]:
    await settle_collections(session, today)
    listings = list(
        await session.scalars(
            select(Listing)
            .where(Listing.seller_id == seller.telegram_id)
            .options(selectinload(Listing.seller))
            .order_by(Listing.created_at.desc())
        )
    )
    return await _pack(session, listings, viewer_id=seller.telegram_id, today=today)


async def get_listing(
    session: AsyncSession,
    listing_id: int,
    *,
    viewer_id: int,
    today: date,
) -> dict[str, object]:
    await settle_collections(session, today)
    listing = await _load(session, listing_id)
    packed = await _pack(session, [listing], viewer_id=viewer_id, today=today)
    return packed[0]


async def create_member_listing(
    session: AsyncSession,
    seller: User,
    *,
    title: str,
    summary: str,
    description: str,
    category: str,
    tags: list[str],
    currency: str,
    price: int,
    kind: str,
    batch_threshold: int | None,
    collection_ends_on: date | None,
    today: date,
) -> Listing:
    _require_member(seller)
    parsed_kind = _parse_kind(kind)
    parsed_currency = _parse_currency(currency)
    _check_price(price, parsed_currency, seller)
    listing = Listing(
        seller_id=seller.telegram_id,
        created_by=seller.telegram_id,
        title=_clean_title(title),
        summary=_clean_summary(summary),
        description=_clean_description(description),
        category=_clean_category(category),
        tags=_clean_tags(tags),
        photos=[],
        kind=parsed_kind,
        currency=parsed_currency,
        price=price,
        stock=0,
        reserved=0,
        status=ListingStatus.ACTIVE,
        collection_phase=CollectionPhase.NONE,
    )
    if parsed_kind is ListingKind.COLLECTIVE:
        if batch_threshold is None or batch_threshold < 2:
            raise MarketError("Порог тиража — от 2 штук")
        if collection_ends_on is None or collection_ends_on < today:
            raise MarketError("Укажи дату окончания набора не раньше сегодня")
        listing.batch_threshold = batch_threshold
        listing.collection_ends_on = collection_ends_on
        listing.collection_phase = CollectionPhase.OPEN
    session.add(listing)
    await session.flush()
    return listing


async def update_member_listing(
    session: AsyncSession,
    seller: User,
    listing_id: int,
    *,
    title: str | None = None,
    summary: str | None = None,
    description: str | None = None,
    category: str | None = None,
    tags: list[str] | None = None,
    currency: str | None = None,
    price: int | None = None,
    batch_threshold: int | None = None,
    collection_ends_on: date | None = None,
    today: date,
) -> Listing:
    listing = await _owned(session, seller, listing_id)
    if title is not None:
        listing.title = _clean_title(title)
    if summary is not None:
        listing.summary = _clean_summary(summary)
    if description is not None:
        listing.description = _clean_description(description)
    if category is not None:
        listing.category = _clean_category(category)
    if tags is not None:
        listing.tags = _clean_tags(tags)
    if currency is not None or price is not None:
        parsed = _parse_currency(currency) if currency is not None else _currency(listing)
        amount = price if price is not None else listing.price
        _check_price(amount, parsed, seller)
        listing.currency = parsed
        listing.price = amount
    if _kind(listing) is ListingKind.COLLECTIVE and _phase(listing) is CollectionPhase.OPEN:
        if batch_threshold is not None:
            if batch_threshold < 2:
                raise MarketError("Порог тиража — от 2 штук")
            listing.batch_threshold = batch_threshold
        if collection_ends_on is not None:
            if collection_ends_on < today:
                raise MarketError("Дата набора не может быть в прошлом")
            listing.collection_ends_on = collection_ends_on
    await session.flush()
    return listing


async def add_photo(session: AsyncSession, seller: User, listing_id: int, relative: str) -> Listing:
    listing = await _owned(session, seller, listing_id)
    photos = list(listing.photos or [])
    if len(photos) >= MAX_PHOTOS:
        raise MarketError(f"На карточке уже {MAX_PHOTOS} фото")
    photos.append(relative)
    listing.photos = photos
    await session.flush()
    return listing


async def create_lab_listing(
    session: AsyncSession,
    actor: User,
    *,
    title: str,
    summary: str,
    description: str,
    category: str,
    tags: list[str],
    currency: str,
    price: int,
) -> Listing:
    require_permission(actor, Permission.FAIR_MODERATE)
    parsed_currency = _parse_currency(currency)
    _check_price(price, parsed_currency, seller=None)
    listing = Listing(
        seller_id=None,
        created_by=actor.telegram_id,
        title=_clean_title(title),
        summary=_clean_summary(summary),
        description=_clean_description(description),
        category=_clean_category(category),
        tags=_clean_tags(tags),
        photos=[],
        kind=ListingKind.REGULAR,
        currency=parsed_currency,
        price=price,
        stock=0,
        reserved=0,
        status=ListingStatus.ACTIVE,
        collection_phase=CollectionPhase.NONE,
    )
    session.add(listing)
    await session.flush()
    return listing


async def add_lab_photo(session: AsyncSession, actor: User, listing_id: int, relative: str) -> None:
    require_permission(actor, Permission.FAIR_MODERATE)
    listing = await _locked(session, listing_id)
    if listing.seller_id is not None:
        raise MarketError("Это карточка участника")
    photos = list(listing.photos or [])
    if len(photos) >= MAX_PHOTOS:
        raise MarketError(f"На карточке уже {MAX_PHOTOS} фото")
    photos.append(relative)
    listing.photos = photos


async def add_stock(session: AsyncSession, actor: User, listing_id: int, quantity: int) -> Listing:
    require_permission(actor, Permission.FAIR_WAREHOUSE)
    if quantity <= 0:
        raise MarketError("Количество приёмки должно быть больше нуля")
    listing = await _locked(session, listing_id)
    if _status(listing) is not ListingStatus.ACTIVE:
        raise MarketError("Карточка снята или закрыта")
    if _kind(listing) is ListingKind.COLLECTIVE and _phase(listing) is not CollectionPhase.READY:
        raise MarketError("Партию принимают на склад после закрытия набора")
    listing.stock = int(listing.stock) + quantity
    await session.flush()
    return listing


async def remove_listing(
    session: AsyncSession,
    actor: User,
    listing_id: int,
    reason: str,
) -> Listing:
    require_permission(actor, Permission.FAIR_MODERATE)
    text = reason.strip()
    if not text:
        raise MarketError("Напиши причину снятия")
    listing = await _locked(session, listing_id)
    if int(listing.reserved) > 0:
        raise MarketError("Есть заказы в резерве. Сначала выдай их или оформи отказ")
    listing.status = ListingStatus.REMOVED
    listing.removal_reason = text[:500]
    listing.removed_by = actor.telegram_id
    await session.flush()
    return listing


async def join_listing(
    session: AsyncSession,
    user: User,
    listing_id: int,
    today: date,
) -> None:
    _require_member(user)
    await settle_collections(session, today)
    listing = await _locked(session, listing_id)
    if not is_joinable(listing, today):
        raise MarketError("Набор по этой карточке закрыт")
    if listing.seller_id == user.telegram_id:
        raise MarketError("Нельзя присоединиться к своей карточке")
    existing = await session.get(ListingPledge, (listing_id, user.telegram_id))
    if existing is not None:
        raise MarketError("Ты уже в наборе")
    session.add(ListingPledge(listing_id=listing_id, user_id=user.telegram_id))
    await session.flush()


async def leave_listing(
    session: AsyncSession,
    user: User,
    listing_id: int,
    today: date,
) -> None:
    await settle_collections(session, today)
    listing = await _load(session, listing_id)
    if not is_joinable(listing, today):
        raise MarketError("Набор уже закрыт, выйти нельзя")
    pledge = await session.get(ListingPledge, (listing_id, user.telegram_id))
    if pledge is None:
        raise MarketError("Тебя нет в наборе")
    await session.delete(pledge)
    await session.flush()


async def set_handover(
    session: AsyncSession,
    seller: User,
    listing_id: int,
    handover_on: date,
    today: date,
) -> Listing:
    await settle_collections(session, today)
    listing = await _owned(session, seller, listing_id)
    if _kind(listing) is not ListingKind.COLLECTIVE or _phase(listing) is not CollectionPhase.READY:
        raise MarketError("Дату привоза ставят, когда тираж уже набран")
    if handover_on < today:
        raise MarketError("Дата привоза не может быть в прошлом")
    listing.handover_on = handover_on
    await session.flush()
    return listing


async def buy(
    session: AsyncSession,
    buyer: User,
    listing_id: int,
    quantity: int,
    today: date,
) -> MarketDeal:
    _require_member(buyer)
    if quantity <= 0:
        raise MarketError("Количество должно быть больше нуля")
    await settle_collections(session, today)
    listing = await _locked(session, listing_id)
    if listing.seller_id == buyer.telegram_id:
        raise MarketError("Нельзя купить свою карточку")
    if not is_buyable(listing):
        raise MarketError("Этого изделия нет на складе")
    if quantity > available(listing):
        raise MarketError("На складе меньше, чем ты хочешь забрать")
    listing.reserved = int(listing.reserved) + quantity
    deal = MarketDeal(
        listing_id=listing.id,
        buyer_id=buyer.telegram_id,
        quantity=quantity,
        unit_price=listing.price,
        currency=_currency(listing),
        status=DealStatus.RESERVED,
        qr_token=await _new_token(session),
    )
    session.add(deal)
    await session.flush()
    return deal


async def list_deals(
    session: AsyncSession,
    user: User,
) -> dict[str, list[dict[str, object]]]:
    bought = list(
        await session.scalars(
            select(MarketDeal)
            .where(MarketDeal.buyer_id == user.telegram_id)
            .options(selectinload(MarketDeal.listing))
            .order_by(MarketDeal.created_at.desc())
        )
    )
    sold: list[MarketDeal] = []
    if user.staff_role is None:
        sold = list(
            await session.scalars(
                select(MarketDeal)
                .join(Listing, Listing.id == MarketDeal.listing_id)
                .where(Listing.seller_id == user.telegram_id)
                .options(selectinload(MarketDeal.listing))
                .order_by(MarketDeal.created_at.desc())
            )
        )
    return {
        "purchases": [_deal_row(item) for item in bought],
        "sales": [_deal_row(item) for item in sold],
    }


async def refuse_deal(
    session: AsyncSession,
    actor: User,
    deal_id: int,
    *,
    as_staff: bool,
) -> MarketDeal:
    if as_staff:
        require_permission(actor, Permission.FAIR_WAREHOUSE)
    deal = await _locked_deal(session, deal_id)
    if not as_staff and deal.buyer_id != actor.telegram_id:
        raise MarketError("Это не твой заказ")
    if deal.status is not DealStatus.RESERVED and str(deal.status) != DealStatus.RESERVED:
        raise MarketError("Отказ возможен только до выдачи")
    listing = await _locked(session, deal.listing_id)
    listing.reserved = max(0, int(listing.reserved) - deal.quantity)
    deal.status = DealStatus.REFUSED
    await session.flush()
    return deal


async def issue_deal(session: AsyncSession, actor: User, token: str) -> MarketDeal:
    require_permission(actor, Permission.FAIR_WAREHOUSE)
    normalized = token.strip().lower()
    if not normalized:
        raise MarketError("Нужен код с QR")
    deal = await session.scalar(
        select(MarketDeal).where(MarketDeal.qr_token == normalized).with_for_update()
    )
    if deal is None:
        raise MarketError("Заказ с таким кодом не найден")
    if deal.status is not DealStatus.RESERVED and str(deal.status) != DealStatus.RESERVED:
        raise MarketError("Этот заказ уже закрыт")
    listing = await _locked(session, deal.listing_id)
    if int(listing.stock) < deal.quantity or int(listing.reserved) < deal.quantity:
        raise MarketError("На складе нет зарезервированных штук")
    grace = _currency_value(deal.currency) is ListingCurrency.GRACE
    if grace:
        await _burn_grace(session, actor, deal)
        await _grant_respect(session, actor, listing, deal)
    listing.stock = int(listing.stock) - deal.quantity
    listing.reserved = int(listing.reserved) - deal.quantity
    deal.status = DealStatus.ISSUED
    deal.issued_by = actor.telegram_id
    deal.issued_at = datetime.now(UTC)
    await session.flush()
    return deal


async def open_dispute(session: AsyncSession, buyer: User, deal_id: int, text: str) -> MarketDeal:
    note = text.strip()
    if not note:
        raise MarketError("Напиши, в чём дело")
    deal = await _locked_deal(session, deal_id)
    if deal.buyer_id != buyer.telegram_id:
        raise MarketError("Спор открывает покупатель")
    if deal.status is not DealStatus.ISSUED and str(deal.status) != DealStatus.ISSUED:
        raise MarketError("Спор открывают после выдачи")
    deal.status = DealStatus.DISPUTED
    deal.dispute_text = note[:2000]
    await session.flush()
    return deal


async def resolve_dispute(
    session: AsyncSession,
    actor: User,
    deal_id: int,
    *,
    return_stock: bool,
) -> MarketDeal:
    require_permission(actor, Permission.FAIR_DISPUTES)
    deal = await _locked_deal(session, deal_id)
    if deal.status is not DealStatus.DISPUTED and str(deal.status) != DealStatus.DISPUTED:
        raise MarketError("Этот заказ не в споре")
    if return_stock:
        listing = await _locked(session, deal.listing_id)
        listing.stock = int(listing.stock) + deal.quantity
        deal.status = DealStatus.RETURNED
    else:
        deal.status = DealStatus.KEPT
    deal.resolved_by = actor.telegram_id
    deal.resolved_at = datetime.now(UTC)
    await session.flush()
    return deal


async def list_disputes(session: AsyncSession) -> list[MarketDeal]:
    return list(
        await session.scalars(
            select(MarketDeal)
            .where(MarketDeal.status == DealStatus.DISPUTED)
            .options(selectinload(MarketDeal.listing), selectinload(MarketDeal.buyer))
            .order_by(MarketDeal.created_at.asc())
        )
    )


async def list_admin_listings(session: AsyncSession) -> list[Listing]:
    return list(
        await session.scalars(
            select(Listing).options(selectinload(Listing.seller)).order_by(Listing.created_at.desc())
        )
    )


async def pledge_user_ids(session: AsyncSession, listing_id: int) -> list[int]:
    rows = await session.scalars(
        select(ListingPledge.user_id).where(ListingPledge.listing_id == listing_id)
    )
    return list(rows)


async def get_deal_for_staff(session: AsyncSession, token: str) -> MarketDeal | None:
    normalized = token.strip().lower()
    if not normalized:
        return None
    found = await session.scalar(
        select(MarketDeal)
        .where(MarketDeal.qr_token == normalized)
        .options(selectinload(MarketDeal.listing), selectinload(MarketDeal.buyer))
    )
    return found


def _deal_row(deal: MarketDeal) -> dict[str, object]:
    title = deal.listing.title if deal.listing is not None else "Изделие"
    svg = qr_svg(deal.qr_token) if str(deal.status) == DealStatus.RESERVED.value else None
    if isinstance(deal.status, DealStatus) and deal.status is DealStatus.RESERVED:
        svg = qr_svg(deal.qr_token)
    return deal_dict(deal, title=title, qr_svg=svg)


async def _pack(
    session: AsyncSession,
    listings: list[Listing],
    *,
    viewer_id: int,
    today: date,
) -> list[dict[str, object]]:
    if not listings:
        return []
    ids = [item.id for item in listings]
    counts = {
        row[0]: int(row[1])
        for row in (
            await session.execute(
                select(ListingPledge.listing_id, func.count())
                .where(ListingPledge.listing_id.in_(ids))
                .group_by(ListingPledge.listing_id)
            )
        ).all()
    }
    joined = set(
        await session.scalars(
            select(ListingPledge.listing_id).where(
                ListingPledge.user_id == viewer_id,
                ListingPledge.listing_id.in_(ids),
            )
        )
    )
    return [
        listing_dict(
            item,
            pledge_count=counts.get(item.id, 0),
            joined=item.id in joined,
            today=today,
        )
        for item in listings
    ]


async def _pledge_count(session: AsyncSession, listing_id: int) -> int:
    value = await session.scalar(
        select(func.count())
        .select_from(ListingPledge)
        .where(ListingPledge.listing_id == listing_id)
    )
    return int(value or 0)


async def _load(session: AsyncSession, listing_id: int) -> Listing:
    listing = await session.scalar(
        select(Listing).where(Listing.id == listing_id).options(selectinload(Listing.seller))
    )
    if listing is None:
        raise MarketError("Карточка не найдена")
    return listing


async def _locked(session: AsyncSession, listing_id: int) -> Listing:
    listing = await session.scalar(
        select(Listing).where(Listing.id == listing_id).with_for_update()
    )
    if listing is None:
        raise MarketError("Карточка не найдена")
    return listing


async def _owned(session: AsyncSession, seller: User, listing_id: int) -> Listing:
    listing = await _locked(session, listing_id)
    if listing.seller_id != seller.telegram_id:
        raise MarketError("Это не твоя карточка")
    if _status(listing) is ListingStatus.REMOVED:
        raise MarketError("Карточка снята")
    return listing


async def _locked_deal(session: AsyncSession, deal_id: int) -> MarketDeal:
    deal = await session.scalar(
        select(MarketDeal).where(MarketDeal.id == deal_id).with_for_update()
    )
    if deal is None:
        raise MarketError("Заказ не найден")
    return deal


async def _new_token(session: AsyncSession) -> str:
    for _ in range(5):
        token = secrets.token_hex(4)
        exists = await session.scalar(select(MarketDeal.id).where(MarketDeal.qr_token == token))
        if exists is None:
            return token
    raise MarketError("Не удалось выдать код заказа")


async def _burn_grace(session: AsyncSession, actor: User, deal: MarketDeal) -> None:
    key = f"market-grace:{deal.id}"
    existing = await session.scalar(select(LedgerEntry).where(LedgerEntry.idempotency_key == key))
    if existing is not None:
        return
    buyer = await session.scalar(
        select(User).where(User.telegram_id == deal.buyer_id).with_for_update()
    )
    if buyer is None:
        raise MarketError("Покупатель не найден")
    total = deal.unit_price * deal.quantity
    if buyer.balance < total:
        raise MarketError("У покупателя не хватает благодати")
    buyer.balance -= total
    session.add(
        LedgerEntry(
            transaction_group=str(uuid.uuid4()),
            idempotency_key=key,
            initiator_id=actor.telegram_id,
            account_user_id=buyer.telegram_id,
            counterparty_id=None,
            delta=-total,
            balance_after=buyer.balance,
            entry_type=LedgerType.MARKET_GRACE,
            reason=f"Ярмарка, выдача #{deal.id}",
        )
    )


async def _grant_respect(
    session: AsyncSession,
    actor: User,
    listing: Listing,
    deal: MarketDeal,
) -> None:
    if listing.seller_id is None:
        return
    key = f"market-respect:{deal.id}"
    existing = await session.scalar(select(LedgerEntry).where(LedgerEntry.idempotency_key == key))
    if existing is not None:
        return
    seller = await session.scalar(
        select(User).where(User.telegram_id == listing.seller_id).with_for_update()
    )
    if seller is None or seller.staff_role is not None:
        return
    seller.respect += GRACE_RESPECT
    session.add(
        LedgerEntry(
            transaction_group=str(uuid.uuid4()),
            idempotency_key=key,
            initiator_id=actor.telegram_id,
            account_user_id=seller.telegram_id,
            delta=GRACE_RESPECT,
            balance_after=seller.respect,
            entry_type=LedgerType.RESPECT_GRANT,
            reason=f"❇ за выдачу на ярмарке #{deal.id}",
        )
    )


def _require_member(user: User) -> None:
    if not user.is_approved:
        raise MarketError("Заявка ещё не одобрена")
    if user.staff_role is not None:
        raise MarketError(
            "Ярмарка для участников. Карточки лаборатории заводит сотрудник в админке"
        )


def _check_price(price: int, currency: ListingCurrency, seller: User | None) -> None:
    if price <= 0:
        raise MarketError("Цена должна быть больше нуля")
    if currency is ListingCurrency.RUB and seller is not None and not seller.sales_mode:
        raise MarketError("Рубли включаются после режима «самозанятый»")


def _clean_title(value: str) -> str:
    text = value.strip()
    if not text or len(text) > 160:
        raise MarketError("Тема карточки — от 1 до 160 символов")
    return text


def _clean_summary(value: str) -> str:
    text = value.strip()
    if not text or len(text) > 400:
        raise MarketError("Краткое описание — от 1 до 400 символов")
    return text


def _clean_description(value: str) -> str:
    text = value.strip()
    if not text:
        raise MarketError("Нужно полное описание")
    return text[:8000]


def _clean_category(value: str) -> str:
    key = value.strip().lower()
    if key not in CATEGORIES:
        raise MarketError("Выбери категорию из списка")
    return key


def _clean_tags(raw: list[str]) -> list[str]:
    cleaned: list[str] = []
    for item in raw:
        text = item.strip()
        if not text or text in cleaned:
            continue
        cleaned.append(text[:24])
        if len(cleaned) >= MAX_TAGS:
            break
    return cleaned


def _parse_kind(value: str) -> ListingKind:
    try:
        return ListingKind(value)
    except ValueError as exc:
        raise MarketError("Тип карточки: обычная или коллективная") from exc


def _parse_currency(value: str) -> ListingCurrency:
    try:
        return ListingCurrency(value)
    except ValueError as exc:
        raise MarketError("Цена либо в благодати, либо в рублях") from exc


def _kind(listing: Listing) -> ListingKind:
    if isinstance(listing.kind, ListingKind):
        return listing.kind
    return ListingKind(str(listing.kind))


def _phase(listing: Listing) -> CollectionPhase:
    if isinstance(listing.collection_phase, CollectionPhase):
        return listing.collection_phase
    return CollectionPhase(str(listing.collection_phase))


def _status(listing: Listing) -> ListingStatus:
    if isinstance(listing.status, ListingStatus):
        return listing.status
    return ListingStatus(str(listing.status))


def _currency(listing: Listing) -> ListingCurrency:
    return _currency_value(listing.currency)


def _currency_value(value: ListingCurrency | str) -> ListingCurrency:
    if isinstance(value, ListingCurrency):
        return value
    return ListingCurrency(str(value))


def _iso(value: date | None) -> str | None:
    return value.isoformat() if value is not None else None
