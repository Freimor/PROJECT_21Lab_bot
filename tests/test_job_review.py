import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from lab21_bot.models import ContentKind, ContentStatus, ServiceJobStatus, User
from lab21_bot.services.jobs import (
    JobError,
    claim_service_job,
    confirm_job_result,
    create_service_job,
    reject_job_result,
    submit_job_result,
)


async def _setup_claimed(session: AsyncSession):
    customer = User(telegram_id=50, full_name="Customer", is_approved=True, balance=300)
    worker = User(
        telegram_id=51,
        full_name="Worker",
        is_approved=True,
        skill_ids=["pcb_design"],
        balance=0,
    )
    session.add_all([customer, worker])
    await session.flush()
    job = await create_service_job(
        session,
        customer_id=customer.telegram_id,
        skill_ids=["pcb_design"],
        description="Развести плату",
        price=120,
        assignee_note="пиши в лс",
    )
    claimed = await claim_service_job(session, job.id, worker)
    return customer, worker, claimed


async def test_job_result_reject_returns_to_claimed(session: AsyncSession) -> None:
    customer, worker, job = await _setup_claimed(session)
    reviewed = await submit_job_result(
        session,
        worker,
        job.id,
        result_text="Готово, gerber в аттаче",
        result_media=[{"type": "photo", "file_id": "AgAC-test"}],
    )
    assert reviewed.status is ServiceJobStatus.REVIEW
    assert reviewed.result_text.startswith("Готово")

    with pytest.raises(JobError):
        await submit_job_result(session, worker, job.id, result_text="ещё раз")

    back = await reject_job_result(session, customer, job.id)
    assert back.status is ServiceJobStatus.CLAIMED
    assert worker.respect == 0


async def test_job_result_confirm_creates_story(session: AsyncSession) -> None:
    customer, worker, job = await _setup_claimed(session)
    await submit_job_result(
        session,
        worker,
        job.id,
        result_text="Собрал и прошил",
        result_media=[{"type": "photo", "file_id": "AgAC-done"}],
    )
    job.job_chat_id = -1001234567890
    job.job_message_id = 42
    await session.flush()

    done, item = await confirm_job_result(session, customer, job.id)
    assert done.status is ServiceJobStatus.DONE
    assert done.content_item_id == item.id
    assert item.kind is ContentKind.STORY
    assert item.status is ContentStatus.MODERATION
    assert item.llm_processed is False
    assert item.source_text.startswith("JOB:")
    assert "Собрал и прошил" in item.source_text
    assert "@" not in item.source_text
    assert "Заказчик: Customer" in item.source_text
    assert "Ссылка на заказ: https://t.me/c/1234567890/42" in item.source_text
    assert item.media == [{"type": "photo", "file_id": "AgAC-done"}]
    assert worker.respect == done.respect_reward
    assert done.reserved is False
