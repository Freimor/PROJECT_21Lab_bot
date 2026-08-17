from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from lab21_bot.models import CommunityRank, StaffRole, User
from lab21_bot.services.applications import (
    ApplicationError,
    create_skill_validation_request,
    request_member_skill,
    resolve_application,
    set_member_rank,
    update_member_skills,
)
from lab21_bot.services.ranks_catalog import ensure_ranks_seeded
from lab21_bot.services.skill_catalog import ensure_skills_seeded


async def _seed(session: AsyncSession) -> tuple[User, User]:
    await ensure_ranks_seeded(session)
    await ensure_skills_seeded(session)
    lord = User(
        telegram_id=1,
        full_name="Lord",
        staff_role=StaffRole.LORD,
        is_approved=True,
    )
    member = User(
        telegram_id=10,
        full_name="Member",
        rank=CommunityRank.NOVICE,
        is_approved=True,
        skill_ids=[],
    )
    session.add_all([lord, member])
    await session.flush()
    return lord, member


@pytest.mark.asyncio
async def test_set_member_rank(session: AsyncSession) -> None:
    lord, member = await _seed(session)
    await set_member_rank(session, lord, member, "adept")
    assert str(member.rank) == "adept"


@pytest.mark.asyncio
async def test_update_member_skills_queues_validation(session: AsyncSession) -> None:
    lord, member = await _seed(session)
    from lab21_bot.data import list_skills
    from lab21_bot.services.applications import list_open_skill_validations

    skills = list_skills()
    needing = [s["id"] for s in skills if s.get("requires_validation")]
    free = [s["id"] for s in skills if not s.get("requires_validation")]
    assert free, "need at least one free skill in catalog"
    assert len(needing) >= 2, "need at least two validation skills"

    desired = [str(free[0]), str(needing[0]), str(needing[1])]
    result = await update_member_skills(session, lord, member, desired)
    assert str(free[0]) in (member.skill_ids or [])
    assert str(needing[0]) not in (member.skill_ids or [])
    assert str(needing[1]) not in (member.skill_ids or [])
    assert set(result.pending_validation) == {str(needing[0]), str(needing[1])}
    apps = await list_open_skill_validations(session, member.telegram_id)
    assert len(apps) == 2
    assert {tuple(app.skill_ids or []) for app in apps} == {
        (str(needing[0]),),
        (str(needing[1]),),
    }


@pytest.mark.asyncio
async def test_request_member_skill_queues_validation(session: AsyncSession) -> None:
    await ensure_ranks_seeded(session)
    await ensure_skills_seeded(session)
    from lab21_bot.data import list_skills
    from lab21_bot.services.applications import get_open_skill_validation

    needing = next(s for s in list_skills() if s.get("requires_validation"))
    member = User(
        telegram_id=12,
        full_name="V",
        is_approved=True,
        skill_ids=[],
    )
    session.add(member)
    await session.flush()
    mode, app = await request_member_skill(session, member, str(needing["id"]))
    assert mode == "validation"
    assert app is not None
    assert str(needing["id"]) not in (member.skill_ids or [])
    pending = await get_open_skill_validation(session, member.telegram_id)
    assert pending is not None
    assert str(needing["id"]) in (pending.skill_ids or [])


@pytest.mark.asyncio
async def test_request_member_skill_instant(session: AsyncSession) -> None:
    await ensure_ranks_seeded(session)
    await ensure_skills_seeded(session)
    from lab21_bot.data import list_skills

    free = next(s for s in list_skills() if not s.get("requires_validation"))
    member = User(
        telegram_id=11,
        full_name="M",
        is_approved=True,
        skill_ids=[],
    )
    session.add(member)
    await session.flush()
    mode, app = await request_member_skill(session, member, str(free["id"]))
    assert mode == "added"
    assert app is None
    assert str(free["id"]) in (member.skill_ids or [])


@pytest.mark.asyncio
async def test_resolve_skill_validation_merges_for_member(session: AsyncSession) -> None:
    lord, member = await _seed(session)
    from lab21_bot.data import list_skills

    needing = [s for s in list_skills() if s.get("requires_validation")]
    if not needing:
        pytest.skip("no validation skills in catalog")
    sid = str(needing[0]["id"])
    free = next(s for s in list_skills() if not s.get("requires_validation"))
    member.skill_ids = [str(free["id"])]
    await session.flush()

    app = await create_skill_validation_request(session, member, [sid])
    await resolve_application(session, lord, app[0].id, approve=True, skill_ids=[sid])
    assert str(free["id"]) in (member.skill_ids or [])
    assert sid in (member.skill_ids or [])
    assert member.balance == 0


@pytest.mark.asyncio
async def test_staff_cannot_request_skill(session: AsyncSession) -> None:
    await ensure_ranks_seeded(session)
    await ensure_skills_seeded(session)
    staff = User(
        telegram_id=2,
        full_name="S",
        staff_role=StaffRole.WATCHER,
        is_approved=True,
    )
    session.add(staff)
    await session.flush()
    with pytest.raises(ApplicationError):
        await request_member_skill(session, staff, "print_3d")
