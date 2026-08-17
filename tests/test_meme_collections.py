import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from lab21_bot.models import ContentTemplate, StaffRole, TemplateKind, User
from lab21_bot.services.templates import (
    TemplateError,
    create_meme_collection,
    create_template,
    delete_meme_collection,
    list_meme_collections,
)


async def test_create_and_list_meme_collections(session: AsyncSession) -> None:
    actor = User(telegram_id=100, full_name="Магистр", staff_role=StaffRole.MAGISTER)
    session.add(actor)
    await session.flush()

    await create_meme_collection(session, actor, "halloween")
    keys = {item.key: item.meme_count for item in await list_meme_collections(session)}
    assert keys["default"] == 0
    assert keys["halloween"] == 0


async def test_delete_collection_moves_memes(session: AsyncSession) -> None:
    actor = User(telegram_id=101, full_name="Магистр", staff_role=StaffRole.MAGISTER)
    session.add(actor)
    await session.flush()

    await create_meme_collection(session, actor, "event")
    await create_template(
        session,
        actor,
        TemplateKind.MEME,
        "Мем один",
        collection_key="event",
    )
    await create_template(
        session,
        actor,
        TemplateKind.MEME,
        "Мем два",
        collection_key="event",
    )

    with pytest.raises(TemplateError, match="перенести"):
        await delete_meme_collection(session, actor, "event")

    moved = await delete_meme_collection(session, actor, "event", move_to="default")
    assert moved == 2
    collections = {item.key: item.meme_count for item in await list_meme_collections(session)}
    assert "event" not in collections
    assert collections["default"] == 2

    rows = list(
        await session.scalars(
            select(ContentTemplate).where(ContentTemplate.kind == TemplateKind.MEME)
        )
    )
    assert all(row.collection_key == "default" for row in rows)


async def test_cannot_delete_default_collection(session: AsyncSession) -> None:
    actor = User(telegram_id=102, full_name="Магистр", staff_role=StaffRole.MAGISTER)
    session.add(actor)
    await session.flush()
    with pytest.raises(TemplateError, match="default"):
        await delete_meme_collection(session, actor, "default")
