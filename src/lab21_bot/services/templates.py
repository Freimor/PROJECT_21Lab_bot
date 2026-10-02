from __future__ import annotations

import random
import re
from dataclasses import dataclass

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from lab21_bot.models import (
    AdminAction,
    BotSetting,
    ContentTemplate,
    MemeCollection,
    SeasonEvent,
    TemplateKind,
    User,
)
from lab21_bot.services.access import Permission, require_permission

_COLLECTION_KEY_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,63}$")
DEFAULT_MEME_COLLECTION = "default"
ACTIVE_MEME_COLLECTIONS_SETTING = "active_meme_collections"


def active_meme_collection_key(season: object | None) -> str:
    """Collection a live season forces. Without a season this is default."""
    if season is None:
        return DEFAULT_MEME_COLLECTION
    key = str(getattr(season, "meme_collection", "") or "").strip()
    return key or DEFAULT_MEME_COLLECTION


def _stored_collection_state(value: object) -> tuple[list[str], int | None]:
    if not isinstance(value, dict):
        return [], None
    keys: list[str] = []
    raw_keys = value.get("keys")
    if isinstance(raw_keys, list):
        for item in raw_keys:
            if not isinstance(item, str):
                continue
            try:
                key = normalize_collection_key(item)
            except TemplateError:
                continue
            if key not in keys:
                keys.append(key)
    raw_season = value.get("season_id")
    season_id = raw_season if isinstance(raw_season, int) else None
    return keys, season_id


async def _save_active_meme_collections(
    session: AsyncSession,
    keys: list[str],
    *,
    season_id: int | None,
    updated_by: int | None = None,
) -> None:
    payload = {"keys": keys, "season_id": season_id}
    row = await session.get(BotSetting, ACTIVE_MEME_COLLECTIONS_SETTING)
    if row is None:
        session.add(
            BotSetting(
                key=ACTIVE_MEME_COLLECTIONS_SETTING,
                value=payload,
                updated_by=updated_by,
            )
        )
    else:
        row.value = payload
        row.updated_by = updated_by
    await session.flush()


async def resolve_active_meme_collections(
    session: AsyncSession,
    season: SeasonEvent | None,
) -> list[str]:
    """Collections autopost may draw from.

    A live season overwrites the saved checkboxes with its own collection.
    After that season ends, the saved choice becomes default.
    """
    row = await session.get(BotSetting, ACTIVE_MEME_COLLECTIONS_SETTING)
    keys, season_id = _stored_collection_state(None if row is None else row.value)
    if season is not None:
        forced = active_meme_collection_key(season)
        if keys != [forced] or season_id != season.id:
            await _save_active_meme_collections(session, [forced], season_id=season.id)
        return [forced]
    if season_id is not None:
        await _save_active_meme_collections(
            session, [DEFAULT_MEME_COLLECTION], season_id=None
        )
        return [DEFAULT_MEME_COLLECTION]
    return keys or [DEFAULT_MEME_COLLECTION]


async def set_active_meme_collections(
    session: AsyncSession,
    actor: User,
    keys: list[str],
    *,
    season: SeasonEvent | None,
) -> list[str]:
    require_permission(actor, Permission.MANAGE_SETTINGS)
    if season is not None:
        raise TemplateError("Сейчас идёт сезонный ивент: коллекцию задаёт он")
    cleaned: list[str] = []
    for raw in keys:
        key = normalize_collection_key(raw)
        if key not in cleaned:
            cleaned.append(key)
    if not cleaned:
        raise TemplateError("Отметьте хотя бы одну коллекцию")
    known = {item.key for item in await list_meme_collections(session)}
    cleaned = [key for key in cleaned if key in known]
    if not cleaned:
        raise TemplateError("Отметьте хотя бы одну коллекцию")
    await _save_active_meme_collections(
        session, cleaned, season_id=None, updated_by=actor.telegram_id
    )
    session.add(
        AdminAction(
            actor_id=actor.telegram_id,
            action="set_active_meme_collections",
            details={"keys": cleaned},
        )
    )
    await session.flush()
    return cleaned


async def _forget_active_meme_collection(session: AsyncSession, key: str) -> None:
    row = await session.get(BotSetting, ACTIVE_MEME_COLLECTIONS_SETTING)
    if row is None:
        return
    keys, season_id = _stored_collection_state(row.value)
    if key not in keys or season_id is not None:
        return
    remaining = [item for item in keys if item != key] or [DEFAULT_MEME_COLLECTION]
    await _save_active_meme_collections(
        session, remaining, season_id=None, updated_by=row.updated_by
    )


class TemplateError(RuntimeError):
    pass


def normalize_collection_key(raw: str | None) -> str:
    key = (raw or "").strip().lower() or DEFAULT_MEME_COLLECTION
    if not _COLLECTION_KEY_RE.fullmatch(key):
        raise TemplateError(
            "Ключ коллекции: латиница, цифры, ._- ; до 64 символов, без пробелов"
        )
    return key


async def ensure_meme_collection(session: AsyncSession, key: str) -> MemeCollection:
    normalized = normalize_collection_key(key)
    existing = await session.get(MemeCollection, normalized)
    if existing is not None:
        return existing
    row = MemeCollection(key=normalized)
    session.add(row)
    await session.flush()
    return row


@dataclass(frozen=True)
class MemeCollectionInfo:
    key: str
    meme_count: int


async def list_meme_collections(session: AsyncSession) -> list[MemeCollectionInfo]:
    await ensure_meme_collection(session, DEFAULT_MEME_COLLECTION)
    counts = dict(
        (
            await session.execute(
                select(ContentTemplate.collection_key, func.count())
                .where(ContentTemplate.kind == TemplateKind.MEME)
                .group_by(ContentTemplate.collection_key)
            )
        ).all()
    )
    keys = list(
        await session.scalars(select(MemeCollection.key).order_by(MemeCollection.key))
    )
    # Keep orphan template keys visible until cleaned up.
    for key in counts:
        normalized = str(key or DEFAULT_MEME_COLLECTION)
        if normalized not in keys:
            keys.append(normalized)
    keys = sorted(set(keys), key=lambda k: (k != DEFAULT_MEME_COLLECTION, k))
    return [
        MemeCollectionInfo(key=key, meme_count=int(counts.get(key, 0) or 0))
        for key in keys
    ]


async def create_meme_collection(session: AsyncSession, actor: User, key: str) -> MemeCollection:
    require_permission(actor, Permission.MANAGE_SETTINGS)
    normalized = normalize_collection_key(key)
    existing = await session.get(MemeCollection, normalized)
    if existing is not None:
        raise TemplateError(f"Коллекция «{normalized}» уже есть")
    row = MemeCollection(key=normalized)
    session.add(row)
    await session.flush()
    return row


async def delete_meme_collection(
    session: AsyncSession,
    actor: User,
    key: str,
    *,
    move_to: str | None = None,
) -> int:
    """Delete a collection registry entry. Moves memes when the pool is not empty.

    Returns number of memes moved.
    """
    require_permission(actor, Permission.MANAGE_SETTINGS)
    source = normalize_collection_key(key)
    if source == DEFAULT_MEME_COLLECTION:
        raise TemplateError("Коллекцию default нельзя удалить")
    row = await session.get(MemeCollection, source)
    count = int(
        await session.scalar(
            select(func.count())
            .select_from(ContentTemplate)
            .where(
                ContentTemplate.kind == TemplateKind.MEME,
                ContentTemplate.collection_key == source,
            )
        )
        or 0
    )
    moved = 0
    if count > 0:
        if not move_to:
            raise TemplateError(
                f"В коллекции «{source}» есть {count} мем(ов). Укажите, куда их перенести."
            )
        target = normalize_collection_key(move_to)
        if target == source:
            raise TemplateError("Нельзя перенести коллекцию саму в себя")
        await ensure_meme_collection(session, target)
        result = await session.execute(
            update(ContentTemplate)
            .where(
                ContentTemplate.kind == TemplateKind.MEME,
                ContentTemplate.collection_key == source,
            )
            .values(collection_key=target)
        )
        moved = int(result.rowcount or 0)
    # Seasons pointing at deleted pool fall back to the move target or default.
    season_target = normalize_collection_key(move_to) if move_to else DEFAULT_MEME_COLLECTION
    if season_target == source:
        season_target = DEFAULT_MEME_COLLECTION
    await ensure_meme_collection(session, season_target)
    await session.execute(
        update(SeasonEvent)
        .where(SeasonEvent.meme_collection == source)
        .values(meme_collection=season_target)
    )
    if row is not None:
        await session.delete(row)
    await _forget_active_meme_collection(session, source)
    await session.flush()
    return moved


async def list_templates(
    session: AsyncSession,
    *,
    kind: TemplateKind | None = None,
) -> list[ContentTemplate]:
    query = (
        select(ContentTemplate)
        .options(selectinload(ContentTemplate.author))
        .order_by(ContentTemplate.kind, ContentTemplate.id)
    )
    if kind is not None:
        query = query.where(ContentTemplate.kind == kind)
    return list(await session.scalars(query))


async def list_meme_collection(
    session: AsyncSession,
    *,
    reactions_asc: bool = True,
    collection_key: str | None = None,
) -> list[ContentTemplate]:
    reaction_order = (
        ContentTemplate.reaction_count.asc()
        if reactions_asc
        else ContentTemplate.reaction_count.desc()
    )
    query = (
        select(ContentTemplate)
        .options(selectinload(ContentTemplate.author))
        .where(ContentTemplate.kind == TemplateKind.MEME)
        .order_by(reaction_order, ContentTemplate.id.desc())
    )
    if collection_key:
        query = query.where(ContentTemplate.collection_key == collection_key)
    return list(await session.scalars(query))


async def list_meme_collection_keys(session: AsyncSession) -> list[str]:
    collections = await list_meme_collections(session)
    return [item.key for item in collections]


async def list_teaser_collection(
    session: AsyncSession,
    *,
    newest_first: bool = True,
) -> list[ContentTemplate]:
    date_order = (
        ContentTemplate.created_at.desc() if newest_first else ContentTemplate.created_at.asc()
    )
    return list(
        await session.scalars(
            select(ContentTemplate)
            .options(selectinload(ContentTemplate.author))
            .where(ContentTemplate.kind == TemplateKind.FLOOD_TEASER)
            .order_by(date_order, ContentTemplate.id.desc())
        )
    )


async def create_template(
    session: AsyncSession,
    actor: User,
    kind: TemplateKind,
    body: str,
    *,
    title: str | None = None,
    author_id: int | None = None,
    collection_key: str = "default",
) -> ContentTemplate:
    require_permission(actor, Permission.MANAGE_SETTINGS)
    text = body.strip()
    if not text:
        raise TemplateError("Текст шаблона пуст")
    if (title or "").strip():
        label = title.strip()
    elif kind is TemplateKind.MEME:
        label = meme_title_from_text(text)
    else:
        label = "Тизер"
    key = normalize_collection_key(collection_key)
    if kind is TemplateKind.MEME:
        await ensure_meme_collection(session, key)
    item = ContentTemplate(
        kind=kind,
        title=label[:160],
        body=text,
        author_id=author_id,
        collection_key=key,
        is_active=True,
    )
    session.add(item)
    await session.flush()
    return item


async def update_template(
    session: AsyncSession,
    actor: User,
    template_id: int,
    *,
    body: str | None = None,
    title: str | None = None,
    is_active: bool | None = None,
    collection_key: str | None = None,
) -> ContentTemplate:
    require_permission(actor, Permission.MANAGE_SETTINGS)
    item = await session.get(ContentTemplate, template_id)
    if item is None:
        raise TemplateError("Шаблон не найден")
    if body is not None:
        text = body.strip()
        if not text:
            raise TemplateError("Текст шаблона пуст")
        item.body = text
    if title is not None:
        label = title.strip()
        if not label:
            raise TemplateError("Название пусто")
        item.title = label[:160]
    if is_active is not None:
        item.is_active = is_active
    if collection_key is not None:
        key = normalize_collection_key(collection_key)
        if item.kind is TemplateKind.MEME:
            await ensure_meme_collection(session, key)
        item.collection_key = key
    await session.flush()
    return item


async def delete_template(session: AsyncSession, actor: User, template_id: int) -> None:
    require_permission(actor, Permission.MANAGE_SETTINGS)
    item = await session.get(ContentTemplate, template_id)
    if item is None:
        raise TemplateError("Шаблон не найден")
    await session.delete(item)
    await session.flush()


TEASER_PLACEHOLDERS: tuple[dict[str, str], ...] = (
    {"token": "{name}", "hint": "Имя автора поста в «Буднях»"},
    {"token": "{username}", "hint": "Ник автора без @; если ника нет — user"},
    {"token": "{link}", "hint": "Ссылка на опубликованный пост"},
)


def render_template(body: str, *, name: str = "", username: str = "", link: str = "") -> str:
    return (
        body.replace("{name}", name or "участник")
        .replace("{username}", username or "user")
        .replace("{link}", link or "")
        .strip()
    )


async def pick_template(
    session: AsyncSession,
    kind: TemplateKind,
    *,
    exclude_id: int | None = None,
    collection_key: str | None = None,
    collection_keys: list[str] | None = None,
) -> ContentTemplate | None:
    if collection_keys:
        keys: list[str] = []
        for raw in collection_keys:
            key = (raw or "").strip() or DEFAULT_MEME_COLLECTION
            if key not in keys:
                keys.append(key)
        if not keys:
            keys = [DEFAULT_MEME_COLLECTION]
    else:
        keys = [(collection_key or DEFAULT_MEME_COLLECTION).strip() or DEFAULT_MEME_COLLECTION]
    catalog = await list_templates(session, kind=kind)

    def matching(*, skip_id: int | None, only: list[str]) -> list[ContentTemplate]:
        return [
            item
            for item in catalog
            if item.is_active
            and (skip_id is None or item.id != skip_id)
            and (item.collection_key or DEFAULT_MEME_COLLECTION) in only
        ]

    items = matching(skip_id=exclude_id, only=keys)
    if not items and DEFAULT_MEME_COLLECTION not in keys:
        items = matching(skip_id=exclude_id, only=[DEFAULT_MEME_COLLECTION])
    if not items:
        items = matching(skip_id=None, only=keys)
    if not items:
        return None
    return random.choice(items)


def meme_title_from_text(text: str, *, fallback: str = "Мем") -> str:
    first = text.strip().splitlines()[0].strip() if text.strip() else ""
    if not first:
        return fallback
    return first[:160]
