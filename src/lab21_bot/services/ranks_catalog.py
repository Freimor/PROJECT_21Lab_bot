from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from lab21_bot.models import AdminAction, Product, RankDef, RoleDef, User
from lab21_bot.services.access import Permission

_ID_RE = re.compile(r"^[a-z][a-z0-9_]{1,62}$")

_DEFAULT_ROLE_PERMISSIONS: dict[str, list[str]] = {
    "lord": [p.value for p in Permission],
    "magister": [p.value for p in Permission if p is not Permission.MANAGE_SYSTEM],
    "tech_priest": [
        Permission.MANAGE_ECONOMY.value,
        Permission.CREATE_STAFF_CONTENT.value,
    ],
    "watcher": [
        Permission.MODERATE_CONTENT.value,
        Permission.MODERATE_ORDERS.value,
        Permission.CREATE_STAFF_CONTENT.value,
    ],
}

_roles_snapshot: list[dict[str, Any]] | None = None
_ranks_snapshot: list[dict[str, Any]] | None = None


class RanksCatalogError(RuntimeError):
    pass


def catalog_key(value: object | None) -> str:
    """Normalize role/rank codes; accept both enum values and legacy UPPER names."""
    if value is None:
        return ""
    if hasattr(value, "value"):
        return str(value.value)
    text = str(value).strip()
    if not text:
        return ""
    lowered = text.lower()
    from lab21_bot.models import CommunityRank, StaffRole

    for enum_cls in (CommunityRank, StaffRole):
        for item in enum_cls:
            if item.value == lowered or item.name.lower() == lowered:
                return item.value
    return lowered


def _json_roles() -> list[dict[str, Any]]:
    from lab21_bot.data import ranks_data

    roles = ranks_data().get("roles") or {}
    if not isinstance(roles, dict):
        return []
    items: list[dict[str, Any]] = []
    for index, (key, item) in enumerate(roles.items()):
        if not isinstance(item, dict):
            continue
        items.append(
            {
                "id": str(key),
                "label": str(item.get("label") or key),
                "badge": str(item.get("badge") or "сотрудник"),
                "color": str(item.get("color") or "#6b7c93"),
                "description": str(item.get("desc") or ""),
                "permissions": list(_DEFAULT_ROLE_PERMISSIONS.get(str(key), [])),
                "is_unique": str(key) == "lord",
                "sort_order": index,
            }
        )
    return items


def _json_ranks() -> list[dict[str, Any]]:
    from lab21_bot.data import ranks_data

    ranks = ranks_data().get("ranks") or {}
    if not isinstance(ranks, dict):
        return []
    items: list[dict[str, Any]] = []
    for index, (key, item) in enumerate(ranks.items()):
        if not isinstance(item, dict):
            continue
        items.append(
            {
                "id": str(key),
                "label": str(item.get("label") or key),
                "level": int(item.get("level") or 0),
                "color": str(item.get("color") or "#a89878"),
                "base_grace": int(item.get("base_grace") or 0),
                "cap_grace": int(item.get("cap_grace") or 0),
                "can_transfer_grace": str(key) == "adept",
                "sort_order": index,
            }
        )
    return items


def role_to_dict(row: RoleDef) -> dict[str, Any]:
    return {
        "id": row.id,
        "label": row.label,
        "badge": row.badge or "сотрудник",
        "color": row.color or "#6b7c93",
        "description": row.description or "",
        "permissions": list(row.permissions or []),
        "is_unique": bool(row.is_unique),
        "sort_order": int(row.sort_order or 0),
    }


def rank_to_dict(row: RankDef) -> dict[str, Any]:
    return {
        "id": row.id,
        "label": row.label,
        "level": int(row.level or 0),
        "color": row.color or "#a89878",
        "base_grace": int(row.base_grace or 0),
        "cap_grace": int(row.cap_grace or 0),
        "can_transfer_grace": bool(row.can_transfer_grace),
        "sort_order": int(row.sort_order or 0),
    }


def get_roles_snapshot() -> list[dict[str, Any]]:
    if _roles_snapshot:
        return list(_roles_snapshot)
    return _json_roles()


def get_ranks_snapshot() -> list[dict[str, Any]]:
    if _ranks_snapshot:
        return list(_ranks_snapshot)
    return _json_ranks()


def clear_ranks_cache() -> None:
    global _roles_snapshot, _ranks_snapshot
    _roles_snapshot = None
    _ranks_snapshot = None


def set_roles_snapshot(rows: list[dict[str, Any]]) -> None:
    global _roles_snapshot
    _roles_snapshot = list(rows)


def set_ranks_snapshot(rows: list[dict[str, Any]]) -> None:
    global _ranks_snapshot
    _ranks_snapshot = list(rows)


async def reload_roles_cache(session: AsyncSession) -> list[dict[str, Any]]:
    rows = await session.scalars(
        select(RoleDef).order_by(RoleDef.sort_order.asc(), RoleDef.label.asc())
    )
    items = [role_to_dict(row) for row in rows]
    set_roles_snapshot(items)
    return items


async def reload_ranks_cache(session: AsyncSession) -> list[dict[str, Any]]:
    rows = await session.scalars(
        select(RankDef).order_by(RankDef.level.asc(), RankDef.sort_order.asc(), RankDef.label.asc())
    )
    items = [rank_to_dict(row) for row in rows]
    set_ranks_snapshot(items)
    return items


async def ensure_ranks_seeded(session: AsyncSession) -> None:
    if await session.scalar(select(RoleDef.id).limit(1)) is None:
        for item in _json_roles():
            session.add(
                RoleDef(
                    id=str(item["id"]),
                    label=str(item["label"]),
                    badge=str(item.get("badge") or "сотрудник"),
                    color=str(item.get("color") or "#6b7c93"),
                    description=str(item.get("description") or ""),
                    permissions=list(item.get("permissions") or []),
                    is_unique=bool(item.get("is_unique")),
                    sort_order=int(item.get("sort_order") or 0),
                )
            )
        await session.flush()
    if await session.scalar(select(RankDef.id).limit(1)) is None:
        for item in _json_ranks():
            session.add(
                RankDef(
                    id=str(item["id"]),
                    label=str(item["label"]),
                    level=int(item.get("level") or 0),
                    color=str(item.get("color") or "#a89878"),
                    base_grace=int(item.get("base_grace") or 0),
                    cap_grace=int(item.get("cap_grace") or 0),
                    can_transfer_grace=bool(item.get("can_transfer_grace")),
                    sort_order=int(item.get("sort_order") or 0),
                )
            )
        await session.flush()
    await reload_roles_cache(session)
    await reload_ranks_cache(session)


def validate_catalog_id(value: str, *, kind: str) -> str:
    text = value.strip().lower()
    if not _ID_RE.match(text):
        raise RanksCatalogError(
            f"ID {kind}: латиница, цифры и _, от 2 символов, начинается с буквы"
        )
    return text


def rank_by_id(rank_id: str) -> dict[str, Any] | None:
    needle = catalog_key(rank_id)
    for item in get_ranks_snapshot():
        if catalog_key(item["id"]) == needle:
            return item
    return None


def role_by_id(role_id: str) -> dict[str, Any] | None:
    needle = catalog_key(role_id)
    for item in get_roles_snapshot():
        if catalog_key(item["id"]) == needle:
            return item
    return None


def permissions_for_role(role_id: str | None) -> frozenset[Permission]:
    if not role_id:
        return frozenset()
    item = role_by_id(str(role_id))
    if item is None:
        return frozenset()
    result: set[Permission] = set()
    for raw in item.get("permissions") or []:
        try:
            result.add(Permission(str(raw)))
        except ValueError:
            continue
    return frozenset(result)


def normalize_permissions(raw: list[str] | None) -> list[str]:
    allowed = {p.value for p in Permission}
    cleaned: list[str] = []
    for item in raw or []:
        value = str(item).strip()
        if value in allowed and value not in cleaned:
            cleaned.append(value)
    return cleaned


PERMISSION_LABELS: dict[str, str] = {
    Permission.MANAGE_STAFF.value: "Управление сотрудниками",
    Permission.MANAGE_SETTINGS.value: "Системные настройки",
    Permission.MANAGE_SYSTEM.value: "Обновление и перезагрузка",
    Permission.MANAGE_STORE.value: "Магазин",
    Permission.MANAGE_ECONOMY.value: "Экономика",
    Permission.MODERATE_CONTENT.value: "Модерация контента",
    Permission.MODERATE_ORDERS.value: "Заказы",
    Permission.CREATE_STAFF_CONTENT.value: "Служебные посты",
}


@dataclass(frozen=True, slots=True)
class RoleRow:
    role: dict[str, Any]
    member_count: int


@dataclass(frozen=True, slots=True)
class RankRow:
    rank: dict[str, Any]
    member_count: int


async def count_role_members(session: AsyncSession) -> dict[str, int]:
    rows = await session.execute(
        select(User.staff_role, func.count())
        .where(User.staff_role.is_not(None), User.is_active.is_(True))
        .group_by(User.staff_role)
    )
    return {catalog_key(role): int(count) for role, count in rows.all() if role}


async def count_rank_members(session: AsyncSession) -> dict[str, int]:
    rows = await session.execute(
        select(User.rank, func.count())
        .where(User.is_approved.is_(True), User.is_active.is_(True), User.staff_role.is_(None))
        .group_by(User.rank)
    )
    return {catalog_key(rank): int(count) for rank, count in rows.all() if rank}


async def list_role_rows(session: AsyncSession) -> list[RoleRow]:
    roles = await reload_roles_cache(session)
    counts = await count_role_members(session)
    return [RoleRow(role=item, member_count=counts.get(str(item["id"]), 0)) for item in roles]


async def list_rank_rows(session: AsyncSession) -> list[RankRow]:
    ranks = await reload_ranks_cache(session)
    counts = await count_rank_members(session)
    return [RankRow(rank=item, member_count=counts.get(str(item["id"]), 0)) for item in ranks]


async def get_role(session: AsyncSession, role_id: str) -> RoleDef | None:
    return await session.get(RoleDef, role_id)


async def get_rank(session: AsyncSession, rank_id: str) -> RankDef | None:
    return await session.get(RankDef, rank_id)


async def create_role(
    session: AsyncSession,
    actor_id: int,
    *,
    role_id: str,
    label: str,
    badge: str = "сотрудник",
    color: str = "#6b7c93",
    description: str = "",
    permissions: list[str] | None = None,
    is_unique: bool = False,
    sort_order: int = 0,
) -> RoleDef:
    role_id = validate_catalog_id(role_id, kind="роли")
    label = label.strip()
    if not label:
        raise RanksCatalogError("Укажи название роли")
    if await session.get(RoleDef, role_id) is not None:
        raise RanksCatalogError("Роль с таким ID уже есть")
    row = RoleDef(
        id=role_id,
        label=label,
        badge=(badge or "сотрудник").strip() or "сотрудник",
        color=(color or "#6b7c93").strip() or "#6b7c93",
        description=description.strip(),
        permissions=normalize_permissions(permissions),
        is_unique=is_unique,
        sort_order=sort_order,
    )
    session.add(row)
    session.add(
        AdminAction(
            actor_id=actor_id,
            action="role_create",
            details={"role_id": role_id, "label": label},
        )
    )
    await session.flush()
    await reload_roles_cache(session)
    return row


async def update_role(
    session: AsyncSession,
    actor_id: int,
    role_id: str,
    *,
    label: str,
    badge: str = "сотрудник",
    color: str = "#6b7c93",
    description: str = "",
    permissions: list[str] | None = None,
    is_unique: bool = False,
    sort_order: int = 0,
) -> RoleDef:
    row = await session.get(RoleDef, role_id)
    if row is None:
        raise RanksCatalogError("Роль не найдена")
    label = label.strip()
    if not label:
        raise RanksCatalogError("Укажи название роли")
    row.label = label
    row.badge = (badge or "сотрудник").strip() or "сотрудник"
    row.color = (color or "#6b7c93").strip() or "#6b7c93"
    row.description = description.strip()
    row.permissions = normalize_permissions(permissions)
    row.is_unique = is_unique
    row.sort_order = sort_order
    session.add(
        AdminAction(
            actor_id=actor_id,
            action="role_update",
            details={"role_id": role_id, "label": label},
        )
    )
    await session.flush()
    await reload_roles_cache(session)
    return row


async def delete_role(session: AsyncSession, actor_id: int, role_id: str) -> None:
    row = await session.get(RoleDef, role_id)
    if row is None:
        raise RanksCatalogError("Роль не найдена")
    in_use = await session.scalar(
        select(func.count()).select_from(User).where(User.staff_role == role_id)
    )
    if in_use:
        raise RanksCatalogError(f"Нельзя удалить: роль назначена {in_use} пользователям")
    label = row.label
    await session.delete(row)
    session.add(
        AdminAction(
            actor_id=actor_id,
            action="role_delete",
            details={"role_id": role_id, "label": label},
        )
    )
    await session.flush()
    await reload_roles_cache(session)


async def create_rank(
    session: AsyncSession,
    actor_id: int,
    *,
    rank_id: str,
    label: str,
    level: int = 0,
    color: str = "#a89878",
    base_grace: int = 0,
    cap_grace: int = 0,
    can_transfer_grace: bool = False,
    sort_order: int = 0,
) -> RankDef:
    rank_id = validate_catalog_id(rank_id, kind="ранга")
    label = label.strip()
    if not label:
        raise RanksCatalogError("Укажи название ранга")
    if await session.get(RankDef, rank_id) is not None:
        raise RanksCatalogError("Ранг с таким ID уже есть")
    if level < 0 or base_grace < 0 or cap_grace < 0:
        raise RanksCatalogError("Уровень и благодать не могут быть отрицательными")
    if cap_grace and base_grace and cap_grace < base_grace:
        raise RanksCatalogError("Потолок благодати не может быть ниже базы")
    row = RankDef(
        id=rank_id,
        label=label,
        level=level,
        color=(color or "#a89878").strip() or "#a89878",
        base_grace=base_grace,
        cap_grace=cap_grace,
        can_transfer_grace=can_transfer_grace,
        sort_order=sort_order,
    )
    session.add(row)
    session.add(
        AdminAction(
            actor_id=actor_id,
            action="rank_create",
            details={"rank_id": rank_id, "label": label},
        )
    )
    await session.flush()
    await reload_ranks_cache(session)
    return row


async def update_rank(
    session: AsyncSession,
    actor_id: int,
    rank_id: str,
    *,
    label: str,
    level: int = 0,
    color: str = "#a89878",
    base_grace: int = 0,
    cap_grace: int = 0,
    can_transfer_grace: bool = False,
    sort_order: int = 0,
) -> RankDef:
    row = await session.get(RankDef, rank_id)
    if row is None:
        raise RanksCatalogError("Ранг не найден")
    label = label.strip()
    if not label:
        raise RanksCatalogError("Укажи название ранга")
    if level < 0 or base_grace < 0 or cap_grace < 0:
        raise RanksCatalogError("Уровень и благодать не могут быть отрицательными")
    if cap_grace and base_grace and cap_grace < base_grace:
        raise RanksCatalogError("Потолок благодати не может быть ниже базы")
    row.label = label
    row.level = level
    row.color = (color or "#a89878").strip() or "#a89878"
    row.base_grace = base_grace
    row.cap_grace = cap_grace
    row.can_transfer_grace = can_transfer_grace
    row.sort_order = sort_order
    session.add(
        AdminAction(
            actor_id=actor_id,
            action="rank_update",
            details={"rank_id": rank_id, "label": label},
        )
    )
    await session.flush()
    await reload_ranks_cache(session)
    return row


async def delete_rank(session: AsyncSession, actor_id: int, rank_id: str) -> None:
    row = await session.get(RankDef, rank_id)
    if row is None:
        raise RanksCatalogError("Ранг не найден")
    total = await session.scalar(select(func.count()).select_from(RankDef))
    if total is not None and int(total) <= 1:
        raise RanksCatalogError("Нельзя удалить последний ранг")
    users = await session.scalar(
        select(func.count()).select_from(User).where(User.rank == rank_id)
    )
    if users:
        raise RanksCatalogError(f"Нельзя удалить: ранг у {users} пользователей")
    products = await session.scalar(
        select(func.count())
        .select_from(Product)
        .where((Product.min_rank == rank_id) | (Product.grants_rank == rank_id))
    )
    if products:
        raise RanksCatalogError(f"Нельзя удалить: ранг используется в {products} товарах")
    label = row.label
    await session.delete(row)
    session.add(
        AdminAction(
            actor_id=actor_id,
            action="rank_delete",
            details={"rank_id": rank_id, "label": label},
        )
    )
    await session.flush()
    await reload_ranks_cache(session)
