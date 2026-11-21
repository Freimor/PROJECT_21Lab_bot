from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from lab21_bot.models import ContentItem, ContentKind, ContentStatus, User
from lab21_bot.services.content import publication_stats


async def test_publication_stats_groups_moderation_queue(session: AsyncSession) -> None:
    author = User(telegram_id=11, full_name="Author", is_approved=True)
    session.add(author)
    await session.flush()
    session.add_all(
        [
            ContentItem(
                author_id=author.telegram_id,
                kind=ContentKind.STORY,
                status=ContentStatus.MODERATION,
                source_text="a",
            ),
            ContentItem(
                author_id=author.telegram_id,
                kind=ContentKind.STORY,
                status=ContentStatus.MODERATION,
                source_text="b",
            ),
            ContentItem(
                author_id=author.telegram_id,
                kind=ContentKind.MEME,
                status=ContentStatus.MODERATION,
                source_text="c",
            ),
            ContentItem(
                author_id=author.telegram_id,
                kind=ContentKind.IMPORTANT,
                status=ContentStatus.SCHEDULED,
                source_text="d",
            ),
        ]
    )
    await session.flush()

    stats = await publication_stats(session, lab_channel_id=-1001)
    assert stats["queue_counts"][ContentKind.STORY.value] == 2
    assert stats["queue_counts"][ContentKind.MEME.value] == 1
    assert stats["queue_counts"][ContentKind.IMPORTANT.value] == 0
    assert stats["queue_total"] == 2
    assert stats["queue_memes"] == 1
    assert stats["scheduled_count"] == 1
