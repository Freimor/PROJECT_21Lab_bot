from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from lab21_bot.models import ServiceJobStatus, User
from lab21_bot.services.chat_ui import normalize_bio, profile_card_html, status_text
from lab21_bot.services.jobs import (
    claim_service_job,
    confirm_job_result,
    count_assignee_done_jobs,
    create_service_job,
    list_job_notify_targets,
    submit_job_result,
)


def test_normalize_bio_trims_and_limits() -> None:
    assert normalize_bio("  hello   world  ") == "hello world"
    try:
        normalize_bio("x" * 501)
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_profile_card_member_uses_sparkle() -> None:
    user = User(
        telegram_id=1,
        full_name="Аким Идрисов",
        is_approved=True,
        rank="novice",
        respect=25,
        skill_ids=["print_3d"],
        bio="Люблю железо",
        job_notify_enabled=True,
        started_at=datetime(2026, 8, 10, tzinfo=UTC),
    )
    html = profile_card_html(user, jobs_done=10, posts=4)
    assert "<b>Аким Идрисов</b>" in html
    assert "25 ❇" in html
    assert "послушник" in html.lower()
    assert "Выполнил заказов — 10" in html
    assert "Публикаций — 4" in html
    assert "Открыт к новым заказам: да" in html
    assert html.index("Публикаций — 4") < html.index("Открыт к новым заказам")
    assert "Люблю железо" in html
    assert "10.08.2026" in html
    assert "Респект" not in html
    assert "25❇" not in html


def test_profile_card_bio_placeholder_for_system_notes() -> None:
    user = User(
        telegram_id=3,
        full_name="Test",
        is_approved=True,
        rank="novice",
        bio="Запрос участника на добавление навыка",
    )
    html = profile_card_html(user, jobs_done=0)
    assert "Участник немногословен..." in html
    assert "Запрос участника" not in html


def test_status_text_includes_open_jobs() -> None:
    user = User(
        telegram_id=2,
        full_name="Test",
        is_approved=True,
        job_notify_enabled=False,
        skill_ids=[],
    )
    text = status_text(user)
    assert "Открыт к заказам: нет" in text
    assert " ❇" in text
    assert "🙏" in text
    assert "Публикаций: 0" in text
    assert "Серия ритуала" not in text


async def test_job_notify_targets_require_open_and_skills(session: AsyncSession) -> None:
    open_fit = User(
        telegram_id=101,
        full_name="OpenFit",
        is_approved=True,
        skill_ids=["print_3d", "pcb_design"],
        job_notify_enabled=True,
    )
    closed = User(
        telegram_id=102,
        full_name="Closed",
        is_approved=True,
        skill_ids=["print_3d", "pcb_design"],
        job_notify_enabled=False,
    )
    missing = User(
        telegram_id=103,
        full_name="Missing",
        is_approved=True,
        skill_ids=["print_3d"],
        job_notify_enabled=True,
    )
    session.add_all([open_fit, closed, missing])
    await session.flush()
    targets = await list_job_notify_targets(session, ["print_3d", "pcb_design"])
    ids = {u.telegram_id for u in targets}
    assert ids == {101}


async def test_count_done_jobs(session: AsyncSession) -> None:
    customer = User(telegram_id=201, full_name="C", is_approved=True, balance=500)
    worker = User(
        telegram_id=202,
        full_name="W",
        is_approved=True,
        skill_ids=["print_3d"],
        balance=0,
    )
    session.add_all([customer, worker])
    await session.flush()
    job = await create_service_job(
        session,
        customer_id=customer.telegram_id,
        skill_ids=["print_3d"],
        description="print",
        price=50,
    )
    await claim_service_job(session, job.id, worker)
    await submit_job_result(session, worker, job.id, result_text="готово")
    await confirm_job_result(session, customer, job.id)
    assert await count_assignee_done_jobs(session, worker.telegram_id) == 1
    assert job.status is ServiceJobStatus.DONE
