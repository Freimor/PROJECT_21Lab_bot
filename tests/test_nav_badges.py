from lab21_bot.models import (
    CommunityRank,
    ContentItem,
    ContentKind,
    ContentStatus,
    JoinApplication,
    JoinKind,
    JoinStatus,
    Order,
    OrderStatus,
    Product,
    ProductKind,
    ServiceJob,
    ServiceJobStatus,
    StaffRole,
    User,
)
from lab21_bot.services.stats import nav_attention
from sqlalchemy.ext.asyncio import AsyncSession


async def test_nav_attention_counts(session: AsyncSession) -> None:
    staff_actor = User(telegram_id=1, full_name="Lord", staff_role=StaffRole.LORD)
    applicant_staff = User(telegram_id=2, full_name="Cand Staff")
    applicant_comm = User(telegram_id=3, full_name="Cand Comm")
    applicant_skill = User(telegram_id=4, full_name="Cand Skill")
    session.add_all([staff_actor, applicant_staff, applicant_comm, applicant_skill])
    await session.flush()

    from datetime import UTC, datetime, timedelta

    exp = datetime.now(UTC) + timedelta(days=7)
    session.add_all(
        [
            JoinApplication(
                user_id=2,
                kind=JoinKind.STAFF,
                status=JoinStatus.PENDING,
                expires_at=exp,
            ),
            JoinApplication(
                user_id=3,
                kind=JoinKind.COMMUNITY,
                status=JoinStatus.PENDING,
                expires_at=exp,
            ),
            JoinApplication(
                user_id=4,
                kind=JoinKind.COMMUNITY,
                status=JoinStatus.SKILL_VALIDATION,
                expires_at=exp,
            ),
            ContentItem(
                author_id=1,
                kind=ContentKind.STORY,
                status=ContentStatus.MODERATION,
                source_text="x",
            ),
            ContentItem(
                author_id=1,
                kind=ContentKind.MEME,
                status=ContentStatus.MODERATION,
                source_text="m",
            ),
        ]
    )
    product = Product(
        article="A1",
        name="Item",
        description="d",
        price=10,
        kind=ProductKind.MERCH,
        min_rank=CommunityRank.NOVICE,
    )
    session.add(product)
    await session.flush()
    session.add(
        Order(
            idempotency_key="o1",
            buyer_id=3,
            product_id=product.id,
            total_price=10,
            status=OrderStatus.PENDING,
        )
    )
    session.add(
        ServiceJob(
            customer_id=3,
            skill_ids=["solder_master"],
            description="Собрать модуль",
            price=10,
            respect_reward=1,
            status=ServiceJobStatus.OPEN,
        )
    )
    await session.flush()

    badges = await nav_attention(session)
    assert badges.join_staff == 1
    assert badges.join_community == 2
    assert badges.publications == 1
    assert badges.memes == 1
    assert badges.publications_total == 2
    assert badges.jobs == 1
    assert badges.orders == 1
    assert badges.has_shop is True
    assert badges.has_joins is True
