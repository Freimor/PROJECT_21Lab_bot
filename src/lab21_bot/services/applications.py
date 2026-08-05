from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from lab21_bot.models import (
    AdminAction,
    JoinApplication,
    JoinKind,
    JoinStatus,
    RemovalReason,
    StaffRole,
    User,
)
from lab21_bot.services.access import Permission, require_permission


class ApplicationError(RuntimeError):
    pass


def compute_expires_at(now: datetime, expire_days: int) -> datetime:
    """Expire at 23:59:59 UTC on the calendar day `expire_days` from `now`."""
    now_utc = now.astimezone(UTC) if now.tzinfo else now.replace(tzinfo=UTC)
    end_day = now_utc.date() + timedelta(days=expire_days)
    return datetime(end_day.year, end_day.month, end_day.day, 23, 59, 59, tzinfo=UTC)


async def get_pending_application(
    session: AsyncSession,
    user_id: int,
) -> JoinApplication | None:
    return cast(
        JoinApplication | None,
        await session.scalar(
            select(JoinApplication).where(
                JoinApplication.user_id == user_id,
                JoinApplication.status == JoinStatus.PENDING,
            )
        ),
    )


async def submit_application(
    session: AsyncSession,
    user: User,
    kind: JoinKind,
    *,
    expire_days: int = 7,
    now: datetime | None = None,
) -> JoinApplication:
    now = now or datetime.now(UTC)
    if user.is_approved and kind is JoinKind.COMMUNITY:
        raise ApplicationError("Вы уже приняты в сообщество")
    if user.staff_role is not None and kind is JoinKind.STAFF:
        raise ApplicationError("Вы уже сотрудник")
    existing = await get_pending_application(session, user.telegram_id)
    if existing is not None:
        raise ApplicationError("Заявка уже ожидает решения")

    application = JoinApplication(
        user_id=user.telegram_id,
        kind=kind,
        status=JoinStatus.PENDING,
        created_at=now,
        expires_at=compute_expires_at(now, expire_days),
    )
    session.add(application)
    await session.flush()
    return application


async def list_pending_applications(
    session: AsyncSession,
    kind: JoinKind | None = None,
) -> list[JoinApplication]:
    query = (
        select(JoinApplication)
        .where(JoinApplication.status == JoinStatus.PENDING)
        .options(selectinload(JoinApplication.user))
        .order_by(JoinApplication.created_at.asc())
    )
    if kind is not None:
        query = query.where(JoinApplication.kind == kind)
    rows = await session.scalars(query)
    return list(rows)


async def list_community_members(session: AsyncSession) -> list[User]:
    rows = await session.scalars(
        select(User)
        .where(
            User.is_approved.is_(True),
            User.staff_role.is_(None),
            User.is_active.is_(True),
        )
        .order_by(User.full_name)
    )
    return list(rows)


def clear_removal(user: User) -> None:
    user.removal_reason = None
    user.removed_at = None
    user.removed_by = None
    user.is_active = True


async def resolve_application(
    session: AsyncSession,
    actor: User,
    application_id: int,
    *,
    approve: bool,
    staff_role: StaffRole | None = None,
    note: str | None = None,
    now: datetime | None = None,
) -> JoinApplication:
    require_permission(actor, Permission.MANAGE_STAFF)
    now = now or datetime.now(UTC)
    application = await session.scalar(
        select(JoinApplication)
        .where(JoinApplication.id == application_id)
        .options(selectinload(JoinApplication.user))
        .with_for_update()
    )
    if application is None or application.status is not JoinStatus.PENDING:
        raise ApplicationError("Заявка уже обработана или не существует")

    user = application.user
    application.decided_by = actor.telegram_id
    application.decided_at = now
    application.decision_note = note

    if approve:
        if application.kind is JoinKind.STAFF:
            if staff_role is None:
                raise ApplicationError("Для сотрудника нужно выбрать роль")
            user.staff_role = staff_role
            user.balance = 0
            user.respect = 0
        user.is_approved = True
        clear_removal(user)
        application.status = JoinStatus.APPROVED
        action = "approve_join"
    else:
        application.status = JoinStatus.REJECTED
        action = "reject_join"

    session.add(
        AdminAction(
            actor_id=actor.telegram_id,
            action=action,
            target_id=user.telegram_id,
            details={
                "application_id": application.id,
                "kind": application.kind.value,
                "staff_role": staff_role.value if staff_role else None,
            },
        )
    )
    await session.flush()
    return application


async def remove_member(
    session: AsyncSession,
    actor: User,
    target: User,
    reason: RemovalReason,
    *,
    now: datetime | None = None,
) -> User:
    require_permission(actor, Permission.MANAGE_STAFF)
    now = now or datetime.now(UTC)
    if target.telegram_id == actor.telegram_id:
        raise ApplicationError("Нельзя удалить себя")
    if not target.is_approved and target.staff_role is None:
        raise ApplicationError("Пользователь уже не состоит в системе")

    previous_role = target.staff_role.value if target.staff_role else None
    was_approved = target.is_approved
    target.staff_role = None
    target.is_approved = False
    target.is_active = False
    target.removal_reason = reason
    target.removed_at = now
    target.removed_by = actor.telegram_id

    pending = await get_pending_application(session, target.telegram_id)
    if pending is not None:
        pending.status = JoinStatus.REJECTED
        pending.decided_by = actor.telegram_id
        pending.decided_at = now
        pending.decision_note = "Отклонено при удалении пользователя"

    session.add(
        AdminAction(
            actor_id=actor.telegram_id,
            action="remove_member",
            target_id=target.telegram_id,
            details={
                "reason": reason.value,
                "previous_staff_role": previous_role,
                "was_approved": was_approved,
            },
        )
    )
    await session.flush()
    return target


async def expire_pending_applications(
    session: AsyncSession,
    *,
    now: datetime | None = None,
) -> list[JoinApplication]:
    now = now or datetime.now(UTC)
    pending = await session.scalars(
        select(JoinApplication)
        .where(
            JoinApplication.status == JoinStatus.PENDING,
            JoinApplication.expires_at <= now,
        )
        .options(selectinload(JoinApplication.user))
        .with_for_update()
    )
    expired: list[JoinApplication] = []
    for application in pending:
        application.status = JoinStatus.EXPIRED
        application.decided_at = now
        application.decision_note = "Автоматический отказ: срок заявки истёк"
        expired.append(application)
    await session.flush()
    return expired
