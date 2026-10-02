from datetime import date, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from lab21_bot.models import (
    CollectionPhase,
    DealStatus,
    ListingKind,
    ListingStatus,
    StaffRole,
    User,
)
from lab21_bot.services.access import Permission, has_permission
from lab21_bot.services.marketplace import (
    MarketError,
    add_stock,
    buy,
    create_lab_listing,
    create_member_listing,
    enable_sales_mode,
    issue_deal,
    join_listing,
    leave_listing,
    list_market,
    open_dispute,
    refuse_deal,
    remove_listing,
    resolve_dispute,
    set_handover,
)

TODAY = date(2026, 10, 1)


def _member(telegram_id: int, name: str, *, balance: int = 0) -> User:
    return User(
        telegram_id=telegram_id,
        full_name=name,
        is_approved=True,
        balance=balance,
        respect=0,
    )


async def _card(session: AsyncSession, seller: User, **kwargs: object):
    payload = {
        "title": "Плата",
        "summary": "DC-DC модуль",
        "description": "Своя плата, без сети 220 В",
        "category": "boards",
        "tags": ["DCDC"],
        "currency": "grace",
        "price": 40,
        "kind": "regular",
        "batch_threshold": None,
        "collection_ends_on": None,
        "today": TODAY,
    }
    payload.update(kwargs)
    return await create_member_listing(session, seller, **payload)  # type: ignore[arg-type]


async def test_ruble_price_needs_sales_mode(session: AsyncSession) -> None:
    seller = _member(1, "Автор")
    session.add(seller)
    await session.flush()
    with pytest.raises(MarketError, match="самозанят"):
        await _card(session, seller, currency="rub", price=500)
    await enable_sales_mode(seller)
    listing = await _card(session, seller, currency="rub", price=500)
    assert listing.currency.value == "rub"
    assert listing.stock == 0


async def test_grace_sale_burns_balance_and_pays_respect(session: AsyncSession) -> None:
    seller = _member(1, "Автор")
    buyer = _member(2, "Покупатель", balance=100)
    keeper = User(
        telegram_id=3,
        full_name="Склад",
        is_approved=True,
        staff_role=StaffRole.WATCHER,
    )
    session.add_all([seller, buyer, keeper])
    await session.flush()
    assert has_permission(keeper, Permission.FAIR_WAREHOUSE)
    assert has_permission(keeper, Permission.FAIR_DISPUTES)
    assert not has_permission(keeper, Permission.MANAGE_STORE)

    listing = await _card(session, seller, price=40)
    with pytest.raises(MarketError, match="нет на складе"):
        await buy(session, buyer, listing.id, 1, TODAY)

    await add_stock(session, keeper, listing.id, 2)
    deal = await buy(session, buyer, listing.id, 1, TODAY)
    assert listing.reserved == 1
    assert deal.status is DealStatus.RESERVED
    assert deal.qr_token

    await issue_deal(session, keeper, deal.qr_token)
    assert buyer.balance == 60
    assert seller.balance == 0
    assert seller.respect == 1
    assert listing.stock == 1
    assert listing.reserved == 0
    assert deal.status is DealStatus.ISSUED


async def test_counter_refusal_returns_reserve(session: AsyncSession) -> None:
    seller = _member(1, "Автор")
    buyer = _member(2, "Покупатель", balance=100)
    keeper = User(telegram_id=3, full_name="Склад", staff_role=StaffRole.WATCHER, is_approved=True)
    session.add_all([seller, buyer, keeper])
    await session.flush()
    listing = await _card(session, seller)
    await add_stock(session, keeper, listing.id, 1)
    deal = await buy(session, buyer, listing.id, 1, TODAY)
    await refuse_deal(session, keeper, deal.id, as_staff=True)
    assert deal.status is DealStatus.REFUSED
    assert listing.reserved == 0
    assert listing.stock == 1
    assert buyer.balance == 100


async def test_collective_batch_and_failed_close(session: AsyncSession) -> None:
    seller = _member(1, "Автор")
    buyer = _member(2, "Покупатель", balance=80)
    other = _member(4, "Второй")
    keeper = User(telegram_id=3, full_name="Склад", staff_role=StaffRole.WATCHER, is_approved=True)
    session.add_all([seller, buyer, other, keeper])
    await session.flush()
    listing = await _card(
        session,
        seller,
        kind="collective",
        batch_threshold=2,
        collection_ends_on=TODAY,
    )
    assert listing.kind is ListingKind.COLLECTIVE
    await join_listing(session, buyer, listing.id, TODAY)
    await leave_listing(session, buyer, listing.id, TODAY)
    await join_listing(session, buyer, listing.id, TODAY)
    await join_listing(session, other, listing.id, TODAY)

    later = TODAY + timedelta(days=1)
    visible = await list_market(session, viewer_id=buyer.telegram_id, today=later)
    row = next(item for item in visible if item["id"] == listing.id)
    assert row["phase"] == CollectionPhase.READY.value
    assert row["buyable"] is False

    await set_handover(session, seller, listing.id, TODAY + timedelta(days=3), later)
    await add_stock(session, keeper, listing.id, 2)
    deal = await buy(session, buyer, listing.id, 1, later)
    assert deal.quantity == 1

    missed = await _card(
        session,
        seller,
        title="Малый тираж",
        kind="collective",
        batch_threshold=2,
        collection_ends_on=TODAY,
    )
    await join_listing(session, buyer, missed.id, TODAY)
    await list_market(session, viewer_id=buyer.telegram_id, today=later)
    assert missed.status is ListingStatus.CLOSED


async def test_lab_card_and_staff_cannot_buy(session: AsyncSession) -> None:
    lord = User(telegram_id=1, full_name="Лорд", staff_role=StaffRole.LORD, is_approved=True)
    buyer = _member(2, "Покупатель", balance=50)
    session.add_all([lord, buyer])
    await session.flush()
    with pytest.raises(MarketError, match="участник"):
        await _card(session, lord)
    listing = await create_lab_listing(
        session,
        lord,
        title="Корпус лабы",
        summary="Печать лабы",
        description="Корпус для стенда",
        category="cases",
        tags=["lab"],
        currency="grace",
        price=10,
    )
    assert listing.seller_id is None
    keeper = User(telegram_id=3, full_name="Склад", staff_role=StaffRole.WATCHER, is_approved=True)
    session.add(keeper)
    await session.flush()
    await add_stock(session, keeper, listing.id, 1)
    with pytest.raises(MarketError, match="участников"):
        await buy(session, lord, listing.id, 1, TODAY)
    deal = await buy(session, buyer, listing.id, 1, TODAY)
    await issue_deal(session, keeper, deal.qr_token)
    assert buyer.balance == 40
    assert buyer.respect == 0


async def test_dispute_return_restocks(session: AsyncSession) -> None:
    seller = _member(1, "Автор")
    buyer = _member(2, "Покупатель", balance=100)
    keeper = User(telegram_id=3, full_name="Склад", staff_role=StaffRole.WATCHER, is_approved=True)
    session.add_all([seller, buyer, keeper])
    await session.flush()
    listing = await _card(session, seller, price=20)
    await add_stock(session, keeper, listing.id, 1)
    deal = await buy(session, buyer, listing.id, 1, TODAY)
    with pytest.raises(MarketError, match="резерве"):
        await remove_listing(session, keeper, listing.id, "рано")
    await issue_deal(session, keeper, deal.qr_token)
    await open_dispute(session, buyer, deal.id, "Не та ревизия платы")
    await resolve_dispute(session, keeper, deal.id, return_stock=True)
    assert deal.status is DealStatus.RETURNED
    assert listing.stock == 1
    assert buyer.balance == 80
