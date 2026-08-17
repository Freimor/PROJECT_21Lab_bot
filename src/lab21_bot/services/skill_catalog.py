from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from lab21_bot.models import AdminAction, SkillDef, User

_SKILL_ID_RE = re.compile(r"^[a-z][a-z0-9_]{1,62}$")

_snapshot: list[dict[str, Any]] | None = None


class SkillCatalogError(RuntimeError):
    pass


def _json_fallback() -> list[dict[str, Any]]:
    from lab21_bot.data import skills_data

    skills = skills_data().get("skills", [])
    return [item for item in skills if isinstance(item, dict) and item.get("id")]


def skill_to_dict(row: SkillDef) -> dict[str, Any]:
    return {
        "id": row.id,
        "title": row.title,
        "description": row.description or "",
        "requires_validation": bool(row.requires_validation),
        "validation_description": row.validation_description or "",
        "level": int(row.level or 1),
        "grace_price": int(row.grace_price or 0),
        "respect_reward": int(row.respect_reward or 0),
    }


def get_skills_snapshot() -> list[dict[str, Any]]:
    if _snapshot:
        return list(_snapshot)
    return _json_fallback()


def clear_skills_cache() -> None:
    global _snapshot
    _snapshot = None


def set_skills_snapshot(rows: list[dict[str, Any]]) -> None:
    global _snapshot
    _snapshot = list(rows)


async def reload_skills_cache(session: AsyncSession) -> list[dict[str, Any]]:
    rows = await session.scalars(select(SkillDef).order_by(SkillDef.level.asc(), SkillDef.title.asc()))
    items = [skill_to_dict(row) for row in rows]
    set_skills_snapshot(items)
    return items


async def ensure_skills_seeded(session: AsyncSession) -> list[dict[str, Any]]:
    existing = await session.scalar(select(SkillDef.id).limit(1))
    if existing is None:
        for item in _json_fallback():
            session.add(
                SkillDef(
                    id=str(item["id"]),
                    title=str(item.get("title") or item["id"]),
                    description=str(item.get("description") or ""),
                    requires_validation=bool(item.get("requires_validation")),
                    validation_description=str(item.get("validation_description") or ""),
                    level=int(item.get("level") or 1),
                    grace_price=int(item.get("grace_price") or 0),
                    respect_reward=int(item.get("respect_reward") or 0),
                )
            )
        await session.flush()
    return await reload_skills_cache(session)


def validate_skill_id(skill_id: str) -> str:
    value = skill_id.strip().lower()
    if not _SKILL_ID_RE.match(value):
        raise SkillCatalogError(
            "ID навыка: латиница, цифры и _, от 2 символов, начинается с буквы"
        )
    return value


@dataclass(frozen=True, slots=True)
class SkillRow:
    skill: dict[str, Any]
    member_count: int


async def count_skill_members(session: AsyncSession) -> dict[str, int]:
    users = await session.scalars(
        select(User).where(User.is_approved.is_(True), User.is_active.is_(True))
    )
    counts: dict[str, int] = {}
    for user in users:
        for skill_id in user.skill_ids or []:
            key = str(skill_id)
            counts[key] = counts.get(key, 0) + 1
    return counts


async def list_skill_rows(
    session: AsyncSession,
    *,
    sort: str = "level",
    sort_asc: bool = True,
) -> list[SkillRow]:
    skills = await reload_skills_cache(session)
    counts = await count_skill_members(session)
    rows = [SkillRow(skill=item, member_count=counts.get(str(item["id"]), 0)) for item in skills]

    reverse = not sort_asc
    if sort == "grace":
        rows.sort(key=lambda row: (int(row.skill.get("grace_price") or 0), str(row.skill.get("title"))), reverse=reverse)
    elif sort == "respect":
        rows.sort(
            key=lambda row: (int(row.skill.get("respect_reward") or 0), str(row.skill.get("title"))),
            reverse=reverse,
        )
    elif sort == "count":
        rows.sort(key=lambda row: (row.member_count, str(row.skill.get("title"))), reverse=reverse)
    elif sort == "title":
        rows.sort(key=lambda row: str(row.skill.get("title") or "").lower(), reverse=reverse)
    else:
        rows.sort(
            key=lambda row: (int(row.skill.get("level") or 0), str(row.skill.get("title"))),
            reverse=reverse,
        )
    return rows


async def get_skill(session: AsyncSession, skill_id: str) -> SkillDef | None:
    return await session.get(SkillDef, skill_id)


async def create_skill(
    session: AsyncSession,
    actor_id: int,
    *,
    skill_id: str,
    title: str,
    description: str = "",
    requires_validation: bool = False,
    validation_description: str = "",
    level: int = 1,
    grace_price: int = 0,
    respect_reward: int = 0,
) -> SkillDef:
    skill_id = validate_skill_id(skill_id)
    title = title.strip()
    if not title:
        raise SkillCatalogError("Укажи название навыка")
    if await session.get(SkillDef, skill_id) is not None:
        raise SkillCatalogError("Навык с таким ID уже есть")
    if level < 1:
        raise SkillCatalogError("Ранг навыка должен быть ≥ 1")
    if grace_price < 0 or respect_reward < 0:
        raise SkillCatalogError("Цены не могут быть отрицательными")

    row = SkillDef(
        id=skill_id,
        title=title,
        description=description.strip(),
        requires_validation=requires_validation,
        validation_description=validation_description.strip(),
        level=level,
        grace_price=grace_price,
        respect_reward=respect_reward,
    )
    session.add(row)
    session.add(
        AdminAction(
            actor_id=actor_id,
            action="skill_create",
            details={"skill_id": skill_id, "title": title},
        )
    )
    await session.flush()
    await reload_skills_cache(session)
    return row


async def update_skill(
    session: AsyncSession,
    actor_id: int,
    skill_id: str,
    *,
    title: str,
    description: str = "",
    requires_validation: bool = False,
    validation_description: str = "",
    level: int = 1,
    grace_price: int = 0,
    respect_reward: int = 0,
) -> SkillDef:
    row = await session.get(SkillDef, skill_id)
    if row is None:
        raise SkillCatalogError("Навык не найден")
    title = title.strip()
    if not title:
        raise SkillCatalogError("Укажи название навыка")
    if level < 1:
        raise SkillCatalogError("Ранг навыка должен быть ≥ 1")
    if grace_price < 0 or respect_reward < 0:
        raise SkillCatalogError("Цены не могут быть отрицательными")

    row.title = title
    row.description = description.strip()
    row.requires_validation = requires_validation
    row.validation_description = validation_description.strip()
    row.level = level
    row.grace_price = grace_price
    row.respect_reward = respect_reward
    session.add(
        AdminAction(
            actor_id=actor_id,
            action="skill_update",
            details={"skill_id": skill_id, "title": title},
        )
    )
    await session.flush()
    await reload_skills_cache(session)
    return row


async def delete_skill(session: AsyncSession, actor_id: int, skill_id: str) -> None:
    row = await session.get(SkillDef, skill_id)
    if row is None:
        raise SkillCatalogError("Навык не найден")

    users = await session.scalars(select(User))
    for user in users:
        ids = list(user.skill_ids or [])
        if skill_id in ids:
            user.skill_ids = [item for item in ids if item != skill_id]

    title = row.title
    await session.delete(row)
    session.add(
        AdminAction(
            actor_id=actor_id,
            action="skill_delete",
            details={"skill_id": skill_id, "title": title},
        )
    )
    await session.flush()
    await reload_skills_cache(session)
