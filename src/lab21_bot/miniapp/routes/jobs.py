from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field
from sqlalchemy import or_, select

from lab21_bot.miniapp.deps import ApprovedUser, DbSession, SettingsDep, map_service_error
from lab21_bot.miniapp.serializers import job_to_dict
from lab21_bot.models import ServiceJob, ServiceJobStatus
from lab21_bot.services.job_publish import publish_service_job, sync_job_board_post
from lab21_bot.services.jobs import (
    JobError,
    claim_service_job,
    confirm_job_result,
    create_service_job,
    get_job,
    list_assignee_claimed_jobs,
    reject_job_result,
    submit_job_result,
)
from lab21_bot.telegram_client import create_bot

router = APIRouter(tags=["miniapp-jobs"])


class CreateJobBody(BaseModel):
    description: str = Field(min_length=1)
    skill_ids: list[str] = Field(min_length=1)
    price: int = Field(ge=0)
    assignee_note: str = ""
    media: list[dict] = Field(default_factory=list)


class JobResultBody(BaseModel):
    report: str = Field(min_length=1)
    media: list[dict] = Field(default_factory=list)


class JobReviewBody(BaseModel):
    approved: bool


@router.post("/jobs")
async def create_job(
    body: CreateJobBody,
    session: DbSession,
    user: ApprovedUser,
    settings: SettingsDep,
) -> dict:
    try:
        job = await create_service_job(
            session,
            customer_id=user.telegram_id,
            skill_ids=body.skill_ids,
            description=body.description,
            price=body.price,
            media=body.media,
            assignee_note=body.assignee_note,
        )
    except JobError as exc:
        raise map_service_error(exc) from exc
    async with create_bot(settings) as bot:
        await publish_service_job(bot, session, settings, job, user)
        from lab21_bot.services.job_publish import notify_job_subscribers

        await notify_job_subscribers(bot, session, job)
    return job_to_dict(job)


@router.get("/jobs/mine")
async def my_jobs(session: DbSession, user: ApprovedUser) -> dict:
    customer_jobs = await session.scalars(
        select(ServiceJob)
        .where(ServiceJob.customer_id == user.telegram_id)
        .order_by(ServiceJob.created_at.desc())
        .limit(50)
    )
    assignee_jobs = await list_assignee_claimed_jobs(session, user.telegram_id)
    return {
        "as_customer": [job_to_dict(job) for job in customer_jobs],
        "as_assignee": [job_to_dict(job) for job in assignee_jobs],
    }


@router.get("/jobs/{job_id}")
async def get_job_detail(job_id: int, session: DbSession, user: ApprovedUser) -> dict:
    job = await get_job(session, job_id)
    if job is None:
        raise map_service_error(JobError("Заказ не найден"))
    if job.customer_id != user.telegram_id and job.assignee_id != user.telegram_id:
        if user.staff_role is None:
            raise map_service_error(JobError("Нет доступа"), forbidden=True)
    return job_to_dict(job)


@router.post("/jobs/{job_id}/claim")
async def claim_job(
    job_id: int,
    session: DbSession,
    user: ApprovedUser,
    settings: SettingsDep,
) -> dict:
    try:
        job = await claim_service_job(session, job_id, user.telegram_id)
    except JobError as exc:
        raise map_service_error(exc) from exc
    async with create_bot(settings) as bot:
        await sync_job_board_post(bot, session, settings, job)
    return job_to_dict(job)


@router.post("/jobs/{job_id}/result")
async def submit_result(
    job_id: int,
    body: JobResultBody,
    session: DbSession,
    user: ApprovedUser,
    settings: SettingsDep,
) -> dict:
    try:
        job = await submit_job_result(
            session,
            job_id,
            user.telegram_id,
            body.report,
            media=body.media,
        )
    except JobError as exc:
        raise map_service_error(exc) from exc
    async with create_bot(settings) as bot:
        await sync_job_board_post(bot, session, settings, job)
    return job_to_dict(job)


@router.post("/jobs/{job_id}/review")
async def review_job(
    job_id: int,
    body: JobReviewBody,
    session: DbSession,
    user: ApprovedUser,
    settings: SettingsDep,
) -> dict:
    try:
        if body.approved:
            job = await confirm_job_result(session, job_id, user.telegram_id)
        else:
            job = await reject_job_result(session, job_id, user.telegram_id)
    except JobError as exc:
        raise map_service_error(exc) from exc
    async with create_bot(settings) as bot:
        await sync_job_board_post(bot, session, settings, job)
    return job_to_dict(job)
