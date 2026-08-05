from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from lab21_bot.models import (
    CommunityRank,
    ContentItem,
    ContentKind,
    ContentStatus,
    LedgerEntry,
    LedgerType,
    Order,
    OrderStatus,
    Product,
    ProductKind,
    StaffRole,
    User,
)
from lab21_bot.services.stats import dashboard_stats


async def test_dashboard_stats(session: AsyncSession) -> None:
    now = datetime(2026, 8, 5, 12, 0, tzinfo=UTC)
    lord = User(
        telegram_id=1,
        full_name="Lord",
        staff_role=StaffRole.LORD,
        balance=100,
        is_approved=True,
        is_active=True,
    )
    member = User(
        telegram_id=2,
        full_name="Adept",
        rank=CommunityRank.ADEPT,
        balance=50,
        is_active=True,
        is_approved=True,
    )
    inactive = User(
        telegram_id=3,
        full_name="Away",
        balance=0,
        is_active=False,
        is_approved=False,
    )
    product = Product(
        article="LAB-STICKER",
        name="Sticker",
        description="lab",
        price=10,
        stock=5,
        kind=ProductKind.MERCH,
    )
    session.add_all([lord, member, inactive, product])
    await session.flush()

    session.add_all(
        [
            Order(
                idempotency_key="o1",
                buyer_id=2,
                product_id=product.id,
                quantity=1,
                total_price=10,
                status=OrderStatus.PENDING,
                created_at=now,
            ),
            Order(
                idempotency_key="o2",
                buyer_id=2,
                product_id=product.id,
                quantity=1,
                total_price=10,
                status=OrderStatus.FULFILLED,
                created_at=now,
            ),
            ContentItem(
                author_id=2,
                kind=ContentKind.STORY,
                status=ContentStatus.MODERATION,
                source_text="hello",
                draft_text="hello",
            ),
            LedgerEntry(
                transaction_group="g1",
                initiator_id=1,
                account_user_id=2,
                delta=20,
                balance_after=50,
                entry_type=LedgerType.GRANT,
                reason="bonus",
                created_at=now - timedelta(days=2),
            ),
            LedgerEntry(
                transaction_group="g2",
                initiator_id=1,
                account_user_id=2,
                delta=-5,
                balance_after=45,
                entry_type=LedgerType.WITHDRAW,
                reason="fine",
                created_at=now - timedelta(days=10),
            ),
            LedgerEntry(
                transaction_group="g3",
                initiator_id=2,
                account_user_id=2,
                delta=-10,
                balance_after=35,
                entry_type=LedgerType.PURCHASE_RESERVE,
                reason="buy",
                created_at=now - timedelta(days=1),
            ),
        ]
    )
    await session.flush()

    stats = await dashboard_stats(session, now=now)
    assert stats.users_total == 2
    assert stats.users_active == 2
    assert stats.balance_sum == 50
    assert stats.orders_pending == 1
    assert stats.orders_fulfilled == 1
    assert stats.content_moderation == 1
    assert stats.grants_7d == 20
    assert stats.grants_30d == 20
    assert stats.withdraws_7d == 0
    assert stats.withdraws_30d == 5
    assert stats.purchases_7d == 10
    assert stats.purchases_30d == 10
