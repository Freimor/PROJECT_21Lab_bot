from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from lab21_bot.models import StaffRole, User
from lab21_bot.services.skill_catalog import (
    SkillCatalogError,
    create_skill,
    delete_skill,
    ensure_skills_seeded,
    list_skill_rows,
    update_skill,
)


async def test_seed_and_sort_skills(session: AsyncSession) -> None:
    await ensure_skills_seeded(session)
    rows = await list_skill_rows(session, sort="grace", sort_asc=False)
    assert rows
    prices = [int(row.skill["grace_price"]) for row in rows]
    assert prices == sorted(prices, reverse=True)


async def test_create_update_delete_skill(session: AsyncSession) -> None:
    actor = User(telegram_id=1, full_name="Lord", staff_role=StaffRole.LORD, is_approved=True)
    member = User(
        telegram_id=2,
        full_name="Member",
        is_approved=True,
        skill_ids=["tmp_skill"],
    )
    session.add_all([actor, member])
    await session.flush()

    await create_skill(
        session,
        actor.telegram_id,
        skill_id="tmp_skill",
        title="Временный",
        level=2,
        grace_price=55,
        respect_reward=5,
    )
    rows = await list_skill_rows(session, sort="title", sort_asc=True)
    assert any(row.skill["id"] == "tmp_skill" and row.member_count == 1 for row in rows)

    await update_skill(
        session,
        actor.telegram_id,
        "tmp_skill",
        title="Временный+",
        level=3,
        grace_price=70,
        respect_reward=7,
    )
    await delete_skill(session, actor.telegram_id, "tmp_skill")
    assert "tmp_skill" not in (member.skill_ids or [])
    with pytest.raises(SkillCatalogError):
        await update_skill(
            session,
            actor.telegram_id,
            "tmp_skill",
            title="x",
            level=1,
            grace_price=1,
            respect_reward=1,
        )
