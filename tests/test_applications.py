from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from lab21_bot.models import JoinKind, JoinStatus, RemovalReason, StaffRole, User
from lab21_bot.services.access import AccessDenied, require_approved
from lab21_bot.services.applications import (
    ApplicationError,
    compute_expires_at,
    expire_pending_applications,
    remove_member,
    resolve_application,
    submit_application,
)


async def test_submit_and_approve_community(session: AsyncSession) -> None:
    actor = User(
        telegram_id=1,
        full_name="Lord",
        staff_role=StaffRole.LORD,
        is_approved=True,
    )
    applicant = User(telegram_id=2, full_name="Novice", is_approved=False)
    session.add_all([actor, applicant])
    await session.flush()

    application = await submit_application(session, applicant, JoinKind.COMMUNITY, expire_days=7)
    assert application.status is JoinStatus.PENDING

    await resolve_application(session, actor, application.id, approve=True)
    assert applicant.is_approved is True
    assert application.status is JoinStatus.APPROVED


async def test_approve_staff_requires_role(session: AsyncSession) -> None:
    actor = User(
        telegram_id=1,
        full_name="Lord",
        staff_role=StaffRole.LORD,
        is_approved=True,
    )
    applicant = User(telegram_id=2, full_name="Watcher", is_approved=False)
    session.add_all([actor, applicant])
    await session.flush()
    application = await submit_application(session, applicant, JoinKind.STAFF)

    with pytest.raises(ApplicationError, match="роль"):
        await resolve_application(session, actor, application.id, approve=True)

    await resolve_application(
        session,
        actor,
        application.id,
        approve=True,
        staff_role=StaffRole.WATCHER,
    )
    assert applicant.staff_role is StaffRole.WATCHER
    assert applicant.is_approved is True


async def test_expire_pending_applications(session: AsyncSession) -> None:
    applicant = User(telegram_id=2, full_name="Late", is_approved=False)
    session.add(applicant)
    await session.flush()
    now = datetime(2026, 8, 5, tzinfo=UTC)
    application = await submit_application(
        session,
        applicant,
        JoinKind.COMMUNITY,
        expire_days=7,
        now=now - timedelta(days=8),
    )
    expired = await expire_pending_applications(session, now=now)
    assert len(expired) == 1
    assert application.status is JoinStatus.EXPIRED


async def test_require_approved() -> None:
    user = User(telegram_id=3, full_name="Pending", is_approved=False)
    with pytest.raises(AccessDenied):
        require_approved(user)


async def test_expires_at_is_end_of_day(session: AsyncSession) -> None:
    applicant = User(telegram_id=4, full_name="Day", is_approved=False)
    session.add(applicant)
    await session.flush()
    now = datetime(2026, 8, 5, 12, 36, 28, tzinfo=UTC)
    application = await submit_application(
        session,
        applicant,
        JoinKind.COMMUNITY,
        expire_days=7,
        now=now,
    )
    assert application.expires_at == datetime(2026, 8, 12, 23, 59, 59, tzinfo=UTC)
    assert compute_expires_at(now, 7) == application.expires_at


async def test_remove_member_keeps_reason_for_reapply(session: AsyncSession) -> None:
    actor = User(
        telegram_id=1,
        full_name="Lord",
        staff_role=StaffRole.LORD,
        is_approved=True,
    )
    member = User(telegram_id=2, full_name="Member", is_approved=True, balance=40)
    session.add_all([actor, member])
    await session.flush()

    await remove_member(session, actor, member, RemovalReason.RULES)
    assert member.is_approved is False
    assert member.is_active is False
    assert member.removal_reason is RemovalReason.RULES

    application = await submit_application(session, member, JoinKind.COMMUNITY)
    assert member.removal_reason is RemovalReason.RULES

    await resolve_application(session, actor, application.id, approve=True)
    assert member.is_approved is True
    assert member.removal_reason is None
    assert member.removed_at is None


async def test_cannot_remove_self(session: AsyncSession) -> None:
    actor = User(
        telegram_id=1,
        full_name="Lord",
        staff_role=StaffRole.LORD,
        is_approved=True,
    )
    session.add(actor)
    await session.flush()
    with pytest.raises(ApplicationError, match="себя"):
        await remove_member(session, actor, actor, RemovalReason.NONE)
