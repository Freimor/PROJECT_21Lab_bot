from __future__ import annotations

import random
import re
from dataclasses import dataclass

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from lab21_bot.models import ContentTemplate, MemeCollection, SeasonEvent, TemplateKind, User
from lab21_bot.services.access import Permission, require_permission

_COLLECTION_KEY_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,63}$")
DEFAULT_MEME_COLLECTION = "default"


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
) -> ContentTemplate | None:
    key = (collection_key or "default").strip() or "default"
    items = [
        item
        for item in await list_templates(session, kind=kind)
        if item.is_active
        and item.id != exclude_id
        and (item.collection_key or "default") == key
    ]
    if not items and key != "default":
        items = [
            item
            for item in await list_templates(session, kind=kind)
            if item.is_active
            and item.id != exclude_id
            and (item.collection_key or "default") == "default"
        ]
    if not items:
        items = [
            item
            for item in await list_templates(session, kind=kind)
            if item.is_active and (item.collection_key or "default") == key
        ]
    if not items:
        return None
    return random.choice(items)


def meme_title_from_text(text: str, *, fallback: str = "Мем") -> str:
    first = text.strip().splitlines()[0].strip() if text.strip() else ""
    if not first:
        return fallback
    return first[:160]
