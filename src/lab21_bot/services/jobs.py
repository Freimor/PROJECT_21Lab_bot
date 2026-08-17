"""Service job pool: free requests and catalog service purchases."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from lab21_bot.data import skill_by_id, skills_grace_sum, skills_respect_sum
from lab21_bot.models import (
    AdminAction,
    LedgerEntry,
    LedgerType,
    ServiceJob,
    ServiceJobStatus,
    User,
)
from lab21_bot.services.access import Permission, require_permission


class JobError(RuntimeError):
    pass


def validate_skill_ids(raw: list[str] | None) -> list[str]:
    if not raw:
        raise JobError("Выбери хотя бы один навык")
    seen: list[str] = []
    for item in raw:
        skill_id = str(item).strip()
        if not skill_id:
            continue
        if skill_by_id(skill_id) is None:
            raise JobError(f"Неизвестный навык: {skill_id}")
        if skill_id not in seen:
            seen.append(skill_id)
    if not seen:
        raise JobError("Выбери хотя бы один навык")
    return seen


def min_job_price(skill_ids: list[str]) -> int:
    return skills_grace_sum(skill_ids)


def default_job_respect(skill_ids: list[str]) -> int:
    return skills_respect_sum(skill_ids)


async def create_service_job(
    session: AsyncSession,
    *,
    customer_id: int,
    skill_ids: list[str],
    description: str,
    price: int | None = None,
    respect_reward: int | None = None,
    media: list[dict] | None = None,
    product_id: int | None = None,
    order_id: int | None = None,
    assignee_note: str = "",
    reserve_funds: bool = True,
) -> ServiceJob:
    skills = validate_skill_ids(skill_ids)
    text = description.strip()
    if not text:
        raise JobError("Описание заказа обязательно")
    note = (assignee_note or "").strip()
    floor = min_job_price(skills)
    amount = floor if price is None else int(price)
    if amount < floor:
        raise JobError(f"Минимальная стоимость: {floor} 🙏")
    reward = default_job_respect(skills) if respect_reward is None else int(respect_reward)
    if reward < 0:
        raise JobError("❇ не может быть отрицательным")

    reserved = False
    customer: User | None = None
    if reserve_funds and amount > 0:
        customer = await session.scalar(
            select(User).where(User.telegram_id == customer_id).with_for_update()
        )
        if customer is None:
            raise JobError("Заказчик не найден")
        if customer.staff_role is not None:
            raise JobError("У сотрудников нет 🙏")
        if customer.balance < amount:
            raise JobError("Недостаточно 🙏")
        customer.balance -= amount
        reserved = True

    job = ServiceJob(
        customer_id=customer_id,
        skill_ids=skills,
        description=text,
        assignee_note=note,
        media=list(media or []),
        product_id=product_id,
        order_id=order_id,
        price=amount,
        respect_reward=reward,
        reserved=reserved,
        status=ServiceJobStatus.OPEN,
    )
    session.add(job)
    await session.flush()

    if reserved and customer is not None:
        session.add(
            LedgerEntry(
                transaction_group=str(uuid.uuid4()),
                idempotency_key=f"job-reserve:{job.id}",
                initiator_id=customer_id,
                account_user_id=customer_id,
                delta=-amount,
                balance_after=customer.balance,
                entry_type=LedgerType.JOB_RESERVE,
                reason=f"Резерв по заявке на услугу #{job.id}",
            )
        )
        await session.flush()
    return job


async def list_active_jobs(
    session: AsyncSession,
    *,
    limit: int = 100,
) -> list[ServiceJob]:
    rows = await session.scalars(
        select(ServiceJob)
        .where(
            ServiceJob.status.in_(
                [
                    ServiceJobStatus.OPEN,
                    ServiceJobStatus.CLAIMED,
                    ServiceJobStatus.REVIEW,
                ]
            )
        )
        .options(
            selectinload(ServiceJob.customer),
            selectinload(ServiceJob.assignee),
            selectinload(ServiceJob.product),
        )
        .order_by(ServiceJob.created_at.desc())
        .limit(limit)
    )
    return list(rows)


async def get_open_job_by_message(
    session: AsyncSession,
    *,
    chat_id: int,
    message_id: int,
    for_update: bool = False,
) -> ServiceJob | None:
    query = select(ServiceJob).where(
        ServiceJob.job_chat_id == chat_id,
        ServiceJob.job_message_id == message_id,
        ServiceJob.status == ServiceJobStatus.OPEN,
    )
    if for_update:
        query = query.with_for_update()
    return await session.scalar(query)


async def get_job_by_order_id(session: AsyncSession, order_id: int) -> ServiceJob | None:
    return await session.scalar(
        select(ServiceJob).where(ServiceJob.order_id == order_id).order_by(ServiceJob.id.desc())
    )


async def claim_service_job(
    session: AsyncSession,
    job_id: int,
    claimant: User,
) -> ServiceJob:
    job = await session.scalar(
        select(ServiceJob).where(ServiceJob.id == job_id).with_for_update()
    )
    if job is None or job.status is not ServiceJobStatus.OPEN:
        raise JobError("Заказ уже взят или недоступен")
    if claimant.telegram_id == job.customer_id:
        raise JobError("own_job")
    have = set(claimant.skill_ids or [])
    required = list(job.skill_ids or [])
    if not required or not all(skill_id in have for skill_id in required):
        raise JobError("missing_skill")
    job.assignee_id = claimant.telegram_id
    job.status = ServiceJobStatus.CLAIMED
    job.claimed_at = datetime.now(UTC)
    await session.flush()
    return job


async def set_job_message(
    session: AsyncSession,
    job: ServiceJob,
    *,
    chat_id: int,
    message_id: int,
) -> None:
    job.job_chat_id = chat_id
    job.job_message_id = message_id
    await session.flush()


async def list_job_notify_targets(
    session: AsyncSession,
    skill_ids: list[str],
    *,
    exclude_user_id: int | None = None,
) -> list[User]:
    needed = set(skill_ids)
    if not needed:
        return []
    rows = await session.scalars(
        select(User).where(
            User.is_approved.is_(True),
            User.is_active.is_(True),
            User.job_notify_enabled.is_(True),
            User.staff_role.is_(None),
        )
    )
    targets: list[User] = []
    for user in rows:
        if exclude_user_id is not None and user.telegram_id == exclude_user_id:
            continue
        have = set(user.skill_ids or [])
        if needed <= have:
            targets.append(user)
    return targets


async def list_assignee_claimed_jobs(
    session: AsyncSession,
    assignee_id: int,
    *,
    limit: int = 50,
) -> list[ServiceJob]:
    return list(
        await session.scalars(
            select(ServiceJob)
            .where(
                ServiceJob.assignee_id == assignee_id,
                ServiceJob.status == ServiceJobStatus.CLAIMED,
            )
            .options(selectinload(ServiceJob.customer))
            .order_by(ServiceJob.claimed_at.desc().nullslast(), ServiceJob.id.desc())
            .limit(limit)
        )
    )


async def count_assignee_done_jobs(session: AsyncSession, assignee_id: int) -> int:
    from sqlalchemy import func

    value = await session.scalar(
        select(func.count())
        .select_from(ServiceJob)
        .where(
            ServiceJob.assignee_id == assignee_id,
            ServiceJob.status == ServiceJobStatus.DONE,
        )
    )
    return int(value or 0)


async def get_job(session: AsyncSession, job_id: int) -> ServiceJob | None:
    return await session.scalar(
        select(ServiceJob)
        .where(ServiceJob.id == job_id)
        .options(
            selectinload(ServiceJob.customer),
            selectinload(ServiceJob.assignee),
        )
    )


def format_job_story_source(
    job: ServiceJob,
    *,
    customer: User,
    assignee: User,
    job_thread_id: int | None = None,
) -> str:
    from lab21_bot.data import skill_title
    from lab21_bot.services.flood import lab_post_link

    skills = ", ".join(skill_title(sid) for sid in (job.skill_ids or [])) or "—"
    report = (job.result_text or "").strip() or "(без текста)"

    def _label(user: User) -> str:
        # Like meme attribution: display name, never @ping / t.me profile link.
        name = (user.full_name or "").strip()
        if name:
            return name
        if user.username:
            return user.username
        return "участник"

    lines = [
        "JOB:",
        f"Заказ #{job.id}",
        f"Навыки: {skills}",
        f"Оплата: {job.price} 🙏",
        f"Исполнителю: {job.respect_reward} ❇",
        f"Заказчик: {_label(customer)}",
        f"Исполнитель: {_label(assignee)}",
        "",
        "Задача:",
        job.description.strip(),
        "",
        "Отчёт исполнителя:",
        report,
    ]
    link = lab_post_link(
        job.job_chat_id,
        job.job_message_id,
        thread_id=job_thread_id,
    )
    if link:
        lines.extend(["", f"Ссылка на заказ: {link}"])
    return "\n".join(lines)


async def submit_job_result(
    session: AsyncSession,
    assignee: User,
    job_id: int,
    *,
    result_text: str,
    result_media: list[dict] | None = None,
) -> ServiceJob:
    job = await session.scalar(
        select(ServiceJob).where(ServiceJob.id == job_id).with_for_update()
    )
    if job is None:
        raise JobError("Заказ не найден")
    if job.status is not ServiceJobStatus.CLAIMED:
        raise JobError("Сдать результат можно только по заказу в работе")
    if job.assignee_id != assignee.telegram_id:
        raise JobError("Это не твой заказ")
    text = (result_text or "").strip()
    media = list(result_media or [])
    if not text and not media:
        raise JobError("Добавь текст или фото отчёта")
    job.result_text = text
    job.result_media = media
    job.status = ServiceJobStatus.REVIEW
    await session.flush()
    return job


async def reject_job_result(
    session: AsyncSession,
    customer: User,
    job_id: int,
) -> ServiceJob:
    job = await session.scalar(
        select(ServiceJob).where(ServiceJob.id == job_id).with_for_update()
    )
    if job is None:
        raise JobError("Заказ не найден")
    if job.status is not ServiceJobStatus.REVIEW:
        raise JobError("Заказ не ждёт подтверждения")
    if job.customer_id != customer.telegram_id:
        raise JobError("Это не твой заказ")
    job.status = ServiceJobStatus.CLAIMED
    await session.flush()
    return job


async def _pay_job_respect(
    session: AsyncSession,
    actor: User,
    job: ServiceJob,
) -> None:
    if job.assignee_id is None or job.respect_reward <= 0:
        return
    assignee = await session.scalar(
        select(User).where(User.telegram_id == job.assignee_id).with_for_update()
    )
    if assignee is None or assignee.staff_role is not None:
        return
    assignee.respect += job.respect_reward
    session.add(
        LedgerEntry(
            transaction_group=str(uuid.uuid4()),
            idempotency_key=f"job-respect:{job.id}",
            initiator_id=actor.telegram_id,
            account_user_id=assignee.telegram_id,
            delta=job.respect_reward,
            balance_after=assignee.respect,
            entry_type=LedgerType.RESPECT_GRANT,
            reason=f"❇ за услугу #{job.id}",
        )
    )


async def confirm_job_result(
    session: AsyncSession,
    customer: User,
    job_id: int,
    *,
    job_thread_id: int | None = None,
):
    """Customer accepts result: close job, pay respect, queue STORY for Будни."""
    from lab21_bot.models import ContentKind
    from lab21_bot.services.content import submit_for_moderation

    job = await session.scalar(
        select(ServiceJob)
        .where(ServiceJob.id == job_id)
        .with_for_update()
        .options(
            selectinload(ServiceJob.customer),
            selectinload(ServiceJob.assignee),
        )
    )
    if job is None:
        raise JobError("Заказ не найден")
    if job.status is not ServiceJobStatus.REVIEW:
        raise JobError("Заказ не ждёт подтверждения")
    if job.customer_id != customer.telegram_id:
        raise JobError("Это не твой заказ")
    if job.assignee_id is None:
        raise JobError("У заказа нет исполнителя")

    assignee = job.assignee or await session.get(User, job.assignee_id)
    if assignee is None:
        raise JobError("Исполнитель не найден")

    job.status = ServiceJobStatus.DONE
    job.reserved = False
    await _pay_job_respect(session, customer, job)

    source = format_job_story_source(
        job,
        customer=customer,
        assignee=assignee,
        job_thread_id=job_thread_id,
    )
    item = await submit_for_moderation(
        session,
        assignee,
        ContentKind.STORY,
        source,
        source,
        media=list(job.result_media or []),
        llm_processed=False,
    )
    job.content_item_id = item.id
    session.add(
        AdminAction(
            actor_id=customer.telegram_id,
            action="confirm_service_job",
            target_id=job.assignee_id,
            details={"job_id": job.id, "content_item_id": item.id},
        )
    )
    await session.flush()
    return job, item


async def mark_job_done(
    session: AsyncSession,
    actor: User,
    job_id: int,
) -> ServiceJob:
    """Staff force-complete (admin). Pays respect; does not create a story post."""
    require_permission(actor, Permission.MODERATE_ORDERS)
    job = await session.scalar(
        select(ServiceJob).where(ServiceJob.id == job_id).with_for_update()
    )
    if job is None:
        raise JobError("Заявка не найдена")
    if job.status not in {
        ServiceJobStatus.OPEN,
        ServiceJobStatus.CLAIMED,
        ServiceJobStatus.REVIEW,
    }:
        raise JobError("Заявка уже закрыта")
    job.status = ServiceJobStatus.DONE
    job.reserved = False
    await _pay_job_respect(session, actor, job)

    session.add(
        AdminAction(
            actor_id=actor.telegram_id,
            action="complete_service_job",
            target_id=job.customer_id,
            details={
                "job_id": job.id,
                "status": job.status.value,
                "respect_reward": job.respect_reward,
                "assignee_id": job.assignee_id,
            },
        )
    )
    await session.flush()
    return job


async def cancel_job(
    session: AsyncSession,
    actor: User,
    job_id: int,
) -> ServiceJob:
    require_permission(actor, Permission.MODERATE_ORDERS)
    job = await session.scalar(
        select(ServiceJob).where(ServiceJob.id == job_id).with_for_update()
    )
    if job is None:
        raise JobError("Заявка не найдена")
    if job.status not in {
        ServiceJobStatus.OPEN,
        ServiceJobStatus.CLAIMED,
        ServiceJobStatus.REVIEW,
    }:
        raise JobError("Заявка уже закрыта")

    if job.reserved and job.price > 0:
        customer = await session.scalar(
            select(User).where(User.telegram_id == job.customer_id).with_for_update()
        )
        if customer is not None:
            customer.balance += job.price
            session.add(
                LedgerEntry(
                    transaction_group=str(uuid.uuid4()),
                    idempotency_key=f"job-refund:{job.id}",
                    initiator_id=actor.telegram_id,
                    account_user_id=customer.telegram_id,
                    delta=job.price,
                    balance_after=customer.balance,
                    entry_type=LedgerType.JOB_REFUND,
                    reason=f"Возврат по отменённой заявке #{job.id}",
                )
            )
        job.reserved = False

    job.status = ServiceJobStatus.CANCELLED
    session.add(
        AdminAction(
            actor_id=actor.telegram_id,
            action="cancel_service_job",
            target_id=job.customer_id,
            details={"job_id": job.id},
        )
    )
    await session.flush()
    return job
