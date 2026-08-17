from sqlalchemy.ext.asyncio import AsyncSession

from lab21_bot.models import (
    ContentItem,
    ContentKind,
    ContentStatus,
    StaffRole,
    User,
)
from lab21_bot.services.reactions import apply_post_reaction_delta, sync_post_reaction_total


async def _published_story(session: AsyncSession, author: User) -> ContentItem:
    item = ContentItem(
        author_id=author.telegram_id,
        kind=ContentKind.STORY,
        status=ContentStatus.PUBLISHED,
        source_text="Собрал датчик",
        draft_text="Собрал датчик",
        published_channel_id=-100123,
        published_message_id=42,
        reaction_count=0,
    )
    session.add(item)
    await session.flush()
    return item


async def test_reactions_award_respect_to_author(session: AsyncSession) -> None:
    author = User(telegram_id=1, full_name="Инженер", is_approved=True)
    session.add(author)
    await session.flush()
    item = await _published_story(session, author)

    entry = await sync_post_reaction_total(
        session,
        chat_id=-100123,
        message_id=42,
        total_reactions=3,
    )
    assert entry is not None
    assert entry.delta == 3
    assert author.respect == 3
    assert item.reaction_count == 3

    again = await sync_post_reaction_total(
        session,
        chat_id=-100123,
        message_id=42,
        total_reactions=3,
    )
    assert again is None
    assert author.respect == 3

    await sync_post_reaction_total(
        session,
        chat_id=-100123,
        message_id=42,
        total_reactions=5,
    )
    assert author.respect == 5

    await sync_post_reaction_total(
        session,
        chat_id=-100123,
        message_id=42,
        total_reactions=2,
    )
    assert author.respect == 2
    assert item.reaction_count == 2


async def test_reaction_delta_in_group(session: AsyncSession) -> None:
    author = User(telegram_id=10, full_name="Мемолог", is_approved=True)
    session.add(author)
    await session.flush()
    item = ContentItem(
        author_id=author.telegram_id,
        kind=ContentKind.MEME,
        status=ContentStatus.PUBLISHED,
        source_text="шутка",
        published_channel_id=-100999,
        published_message_id=7,
        reaction_count=0,
    )
    session.add(item)
    await session.flush()

    await apply_post_reaction_delta(
        session, chat_id=-100999, message_id=7, delta=1
    )
    assert author.respect == 1
    assert item.reaction_count == 1

    await apply_post_reaction_delta(
        session, chat_id=-100999, message_id=7, delta=-1
    )
    assert author.respect == 0


async def test_staff_author_reactions_ignored(session: AsyncSession) -> None:
    author = User(
        telegram_id=20,
        full_name="Смотрящий",
        staff_role=StaffRole.WATCHER,
        is_approved=True,
    )
    session.add(author)
    await session.flush()
    item = await _published_story(session, author)

    entry = await sync_post_reaction_total(
        session,
        chat_id=-100123,
        message_id=42,
        total_reactions=4,
    )
    assert entry is None
    assert author.respect == 0
    assert item.reaction_count == 4
