from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from lab21_bot.models import CommunityRank, StaffRole, User
from lab21_bot.services.access import Permission, has_permission
from lab21_bot.services.ranks_catalog import (
    RanksCatalogError,
    create_rank,
    create_role,
    delete_rank,
    delete_role,
    ensure_ranks_seeded,
    get_ranks_snapshot,
    get_roles_snapshot,
    update_rank,
    update_role,
)


@pytest.mark.asyncio
async def test_seed_roles_and_ranks(session: AsyncSession) -> None:
    await ensure_ranks_seeded(session)
    roles = {item["id"] for item in get_roles_snapshot()}
    ranks = {item["id"] for item in get_ranks_snapshot()}
    assert "lord" in roles
    assert "watcher" in roles
    assert "novice" in ranks
    assert "adept" in ranks


@pytest.mark.asyncio
async def test_role_crud_and_permissions(session: AsyncSession) -> None:
    await ensure_ranks_seeded(session)
    actor = User(telegram_id=1, full_name="Lord", staff_role=StaffRole.LORD, is_approved=True)
    session.add(actor)
    await session.flush()

    role = await create_role(
        session,
        actor.telegram_id,
        role_id="scribe",
        label="Писец",
        badge="сотрудник",
        color="#445566",
        description="Архивы",
        permissions=[Permission.MODERATE_CONTENT.value],
    )
    assert role.id == "scribe"
    assert any(item["id"] == "scribe" for item in get_roles_snapshot())

    user = User(telegram_id=2, full_name="Scribe", staff_role="scribe", is_approved=True)
    session.add(user)
    await session.flush()
    assert has_permission(user, Permission.MODERATE_CONTENT)
    assert not has_permission(user, Permission.MANAGE_STAFF)

    await update_role(
        session,
        actor.telegram_id,
        "scribe",
        label="Писец+",
        permissions=[Permission.MODERATE_CONTENT.value, Permission.MODERATE_ORDERS.value],
    )
    assert has_permission(user, Permission.MODERATE_ORDERS)

    with pytest.raises(RanksCatalogError):
        await delete_role(session, actor.telegram_id, "scribe")

    user.staff_role = None
    await session.flush()
    await delete_role(session, actor.telegram_id, "scribe")
    assert all(item["id"] != "scribe" for item in get_roles_snapshot())


@pytest.mark.asyncio
async def test_rank_crud(session: AsyncSession) -> None:
    await ensure_ranks_seeded(session)
    actor = User(telegram_id=1, full_name="Lord", staff_role=StaffRole.LORD, is_approved=True)
    session.add(actor)
    await session.flush()

    rank = await create_rank(
        session,
        actor.telegram_id,
        rank_id="initiate",
        label="Посвящённый",
        level=2,
        base_grace=200,
        cap_grace=400,
        can_transfer_grace=True,
    )
    assert rank.id == "initiate"

    await update_rank(
        session,
        actor.telegram_id,
        "initiate",
        label="Посвящённый+",
        level=3,
        base_grace=220,
        cap_grace=440,
        can_transfer_grace=True,
    )
    updated = next(item for item in get_ranks_snapshot() if item["id"] == "initiate")
    assert updated["label"] == "Посвящённый+"
    assert updated["level"] == 3

    member = User(
        telegram_id=3,
        full_name="Member",
        rank=CommunityRank.NOVICE,
        is_approved=True,
    )
    session.add(member)
    await session.flush()
    await delete_rank(session, actor.telegram_id, "initiate")
    assert all(item["id"] != "initiate" for item in get_ranks_snapshot())
