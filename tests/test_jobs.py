from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from lab21_bot.data import list_skills, skill_by_id, skill_requires_validation
from lab21_bot.models import ProductKind, ServiceJobStatus, StaffRole, User
from lab21_bot.services.economy import EconomyError
from lab21_bot.services.jobs import JobError, claim_service_job, create_service_job
from lab21_bot.services.store import create_product, purchase


def test_skills_catalog_loaded() -> None:
    skills = list_skills()
    assert len(skills) >= 5
    assert skill_by_id("pcb_design") is not None
    assert skill_requires_validation("pcb_design") is True
    assert skill_requires_validation("print_3d") is False
    assert skill_by_id("cad_3d_engineer")["grace_price"] == 100
    assert skill_by_id("pcb_design")["validation_description"]
    assert not skill_by_id("print_3d")["validation_description"]


async def test_service_product_requires_skill(session: AsyncSession) -> None:
    lord = User(telegram_id=1, full_name="Lord", staff_role=StaffRole.LORD)
    session.add(lord)
    await session.flush()
    with pytest.raises(EconomyError, match="навык"):
        await create_product(
            session,
            lord,
            article="LAB-SVC",
            name="Пайка",
            description="Пайка модуля",
            price=10,
            stock=None,
            kind=ProductKind.SERVICE,
        )
    product = await create_product(
        session,
        lord,
        article="LAB-SVC",
        name="Пайка",
        description="Пайка модуля",
        price=80,
        stock=None,
        kind=ProductKind.SERVICE,
        skill_ids=["solder_master"],
    )
    assert product.skill_ids == ["solder_master"]


async def test_purchase_service_creates_job(session: AsyncSession) -> None:
    lord = User(telegram_id=1, full_name="Lord", staff_role=StaffRole.LORD)
    buyer = User(telegram_id=3, full_name="Buyer", balance=50, is_approved=True)
    session.add_all([lord, buyer])
    await session.flush()
    product = await create_product(
        session,
        lord,
        article="LAB-JOB",
        name="Сборка",
        description="Собрать корпус",
        price=50,
        stock=None,
        kind=ProductKind.SERVICE,
        skill_ids=["mechanics"],
    )
    order = await purchase(session, buyer.telegram_id, product.id, idempotency_key="svc-1")
    from lab21_bot.services.jobs import get_job_by_order_id

    job = await get_job_by_order_id(session, order.id)
    assert job is not None
    assert job.skill_ids == ["mechanics"]
    assert job.status is ServiceJobStatus.OPEN


async def test_claim_job_requires_all_skills(session: AsyncSession) -> None:
    customer = User(telegram_id=10, full_name="Customer", is_approved=True, balance=200)
    worker = User(
        telegram_id=11,
        full_name="Worker",
        is_approved=True,
        skill_ids=["print_3d"],
    )
    skilled = User(
        telegram_id=12,
        full_name="Skilled",
        is_approved=True,
        skill_ids=["pcb_design", "print_3d"],
    )
    session.add_all([customer, worker, skilled])
    await session.flush()
    job = await create_service_job(
        session,
        customer_id=customer.telegram_id,
        skill_ids=["pcb_design"],
        description="Развести плату",
        price=120,
        assignee_note="Пиши в ЛС @customer, нужен gerber до пятницы",
    )
    assert job.assignee_note.startswith("Пиши в ЛС")
    with pytest.raises(JobError, match="missing_skill"):
        await claim_service_job(session, job.id, worker)
    with pytest.raises(JobError, match="own_job"):
        await claim_service_job(session, job.id, customer)
    claimed = await claim_service_job(session, job.id, skilled)
    assert claimed.status is ServiceJobStatus.CLAIMED
    assert claimed.assignee_id == skilled.telegram_id


def test_job_board_keyboard_follows_status() -> None:
    from lab21_bot.keyboards import job_board_keyboard

    open_kb = job_board_keyboard(7, ServiceJobStatus.OPEN)
    assert open_kb.inline_keyboard[0][0].text == "Взять заказ"
    assert open_kb.inline_keyboard[0][0].callback_data == "job_claim:7"

    busy = job_board_keyboard(7, ServiceJobStatus.CLAIMED)
    assert busy.inline_keyboard[0][0].text == "Заказ в работе"
    review = job_board_keyboard(7, ServiceJobStatus.REVIEW)
    assert review.inline_keyboard[0][0].text == "Заказ в работе"

    done = job_board_keyboard(7, ServiceJobStatus.DONE)
    assert done.inline_keyboard[0][0].text == "Заказ выполнен"

    cancelled = job_board_keyboard(7, ServiceJobStatus.CANCELLED)
    assert cancelled.inline_keyboard[0][0].text == "Заказ отменён"


def test_job_post_html_uses_currency_symbols() -> None:
    from lab21_bot.models import ServiceJob
    from lab21_bot.services.job_publish import format_job_post_html

    customer = User(telegram_id=1, full_name="Заказчик", is_approved=True)
    job = ServiceJob(
        id=9,
        customer_id=1,
        skill_ids=["print_3d"],
        description="Напечатать корпус",
        price=80,
        respect_reward=5,
        status=ServiceJobStatus.OPEN,
    )
    html = format_job_post_html(job, customer)
    assert "80" in html and "🙏" in html
    assert "5" in html and "❇" in html
    assert "благодар" not in html.lower()
    assert "респект" not in html.lower()
    assert "👍" not in html
