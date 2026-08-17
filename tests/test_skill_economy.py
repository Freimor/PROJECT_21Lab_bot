from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from lab21_bot.data import list_skills, rank_base_grace, rank_cap_grace, skills_grace_sum, skills_respect_sum
from lab21_bot.models import (
    JoinKind,
    JoinStatus,
    ProductKind,
    ServiceJobStatus,
    StaffRole,
    User,
)
from lab21_bot.services.applications import resolve_application, submit_application
from lab21_bot.services.economy import EconomyError
from lab21_bot.services.grace_refill import (
    adjust_grace_bounds,
    decay_amount,
    refill_amount,
    refill_grace_toward_base,
)
from lab21_bot.services.jobs import (
    JobError,
    cancel_job,
    claim_service_job,
    create_service_job,
    mark_job_done,
)
from lab21_bot.services.store import create_product, purchase


def test_skill_price_helpers() -> None:
    assert skills_grace_sum(["cad_3d_engineer", "electronics"]) == 200
    assert skills_respect_sum(["cad_3d_engineer", "electronics"]) == 20
    assert rank_base_grace("novice") == 100
    assert rank_base_grace("adept") == 150
    assert rank_cap_grace("novice") == 200
    assert rank_cap_grace("adept") == 300
    assert any(s["id"] == "electronics" for s in list_skills())


def test_refill_amount_caps_at_base() -> None:
    assert refill_amount(balance=90, base=100, percent=5) == 5
    assert refill_amount(balance=98, base=100, percent=5) == 2
    assert refill_amount(balance=100, base=100, percent=5) == 0


def test_decay_amount_caps_at_ceiling() -> None:
    assert decay_amount(balance=210, cap=200, percent=5) == 10
    assert decay_amount(balance=205, cap=200, percent=5) == 5
    assert decay_amount(balance=200, cap=200, percent=5) == 0
    assert decay_amount(balance=150, cap=200, percent=5) == 0
    assert decay_amount(balance=250, cap=0, percent=5) == 0


async def test_free_job_price_floor_and_claim_all_skills(session: AsyncSession) -> None:
    customer = User(telegram_id=10, full_name="Customer", is_approved=True, balance=500)
    weak = User(
        telegram_id=11,
        full_name="Weak",
        is_approved=True,
        skill_ids=["print_3d"],
        balance=0,
    )
    strong = User(
        telegram_id=12,
        full_name="Strong",
        is_approved=True,
        skill_ids=["cad_3d_engineer", "electronics"],
        balance=0,
    )
    watcher = User(
        telegram_id=2,
        full_name="Watcher",
        staff_role=StaffRole.WATCHER,
        is_approved=True,
    )
    session.add_all([customer, weak, strong, watcher])
    await session.flush()

    with pytest.raises(JobError, match="Минимальная"):
        await create_service_job(
            session,
            customer_id=customer.telegram_id,
            skill_ids=["cad_3d_engineer", "electronics"],
            description="Сборка",
            price=150,
        )

    job = await create_service_job(
        session,
        customer_id=customer.telegram_id,
        skill_ids=["cad_3d_engineer", "electronics"],
        description="Сборка",
        price=200,
    )
    assert customer.balance == 300
    assert job.reserved is True
    assert job.respect_reward == 20

    with pytest.raises(JobError, match="missing_skill"):
        await claim_service_job(session, job.id, weak)

    claimed = await claim_service_job(session, job.id, strong)
    assert claimed.status is ServiceJobStatus.CLAIMED

    done = await mark_job_done(session, watcher, job.id)
    assert done.status is ServiceJobStatus.DONE
    assert strong.respect == 20


async def test_cancel_job_refunds(session: AsyncSession) -> None:
    customer = User(telegram_id=20, full_name="C", is_approved=True, balance=100)
    watcher = User(telegram_id=21, full_name="W", staff_role=StaffRole.WATCHER, is_approved=True)
    session.add_all([customer, watcher])
    await session.flush()
    job = await create_service_job(
        session,
        customer_id=customer.telegram_id,
        skill_ids=["print_3d"],
        description="Печать",
        price=40,
    )
    assert customer.balance == 60
    await cancel_job(session, watcher, job.id)
    assert customer.balance == 100
    assert job.status is ServiceJobStatus.CANCELLED


async def test_service_product_multi_skill_and_purchase_job(session: AsyncSession) -> None:
    lord = User(telegram_id=1, full_name="Lord", staff_role=StaffRole.LORD)
    buyer = User(telegram_id=3, full_name="Buyer", balance=300, is_approved=True)
    session.add_all([lord, buyer])
    await session.flush()

    with pytest.raises(EconomyError, match="Минимальная"):
        await create_product(
            session,
            lord,
            article="LAB-LOW",
            name="Дешево",
            description="x",
            price=50,
            stock=None,
            kind=ProductKind.SERVICE,
            skill_ids=["cad_3d_engineer"],
        )

    product = await create_product(
        session,
        lord,
        article="LAB-SVC2",
        name="Инженерия",
        description="CAD",
        price=100,
        stock=None,
        kind=ProductKind.SERVICE,
        skill_ids=["cad_3d_engineer"],
        respect_reward=15,
    )
    assert product.skill_ids == ["cad_3d_engineer"]
    assert product.respect_reward == 15

    order = await purchase(session, buyer.telegram_id, product.id, idempotency_key="p1")
    from lab21_bot.services.jobs import get_job_by_order_id

    job = await get_job_by_order_id(session, order.id)
    assert job is not None
    assert job.reserved is False
    assert job.price == 100
    assert job.respect_reward == 15
    assert buyer.balance == 200


async def test_approve_grants_base_grace(session: AsyncSession) -> None:
    actor = User(telegram_id=1, full_name="Lord", staff_role=StaffRole.LORD, is_approved=True)
    applicant = User(telegram_id=2, full_name="Novice", is_approved=False, balance=0)
    session.add_all([actor, applicant])
    await session.flush()
    application = await submit_application(
        session,
        applicant,
        JoinKind.COMMUNITY,
        bio="hi",
        skills_text="печать",
    )
    await resolve_application(
        session,
        actor,
        application.id,
        approve=True,
        skill_ids=["print_3d"],
    )
    assert application.status is JoinStatus.APPROVED
    assert applicant.balance == 100


async def test_approve_grants_base_grace_with_legacy_rank_name(session: AsyncSession) -> None:
    """Legacy rows may store Enum.name (NOVICE) instead of value (novice)."""
    from lab21_bot.data import rank_base_grace
    from lab21_bot.services.ranks_catalog import catalog_key

    assert catalog_key("NOVICE") == "novice"
    assert rank_base_grace("NOVICE") == 100

    actor = User(telegram_id=1, full_name="Lord", staff_role=StaffRole.LORD, is_approved=True)
    applicant = User(telegram_id=3, full_name="Legacy", is_approved=False, balance=0)
    # Bypass ORM coercion: set raw attribute after flush via SQL-like assignment
    session.add_all([actor, applicant])
    await session.flush()
    await session.execute(
        __import__("sqlalchemy").text("UPDATE users SET rank = 'NOVICE' WHERE telegram_id = 3")
    )
    await session.refresh(applicant)
    application = await submit_application(
        session,
        applicant,
        JoinKind.COMMUNITY,
        bio="hi",
        skills_text="печать",
    )
    await resolve_application(
        session,
        actor,
        application.id,
        approve=True,
        skill_ids=["print_3d"],
    )
    assert applicant.balance == 100
    assert str(applicant.rank) == "novice"


async def test_grace_refill(session: AsyncSession) -> None:
    user = User(
        telegram_id=30,
        full_name="Low",
        is_approved=True,
        balance=90,
    )
    session.add(user)
    await session.flush()
    updated = await refill_grace_toward_base(session)
    assert len(updated) == 1
    assert user.balance == 95


async def test_grace_decay_toward_cap(session: AsyncSession) -> None:
    user = User(
        telegram_id=31,
        full_name="Rich",
        is_approved=True,
        balance=220,
    )
    session.add(user)
    await session.flush()
    refilled, decayed = await adjust_grace_bounds(session)
    assert refilled == []
    assert len(decayed) == 1
    # 5% of cap 200 = 10
    assert user.balance == 210
