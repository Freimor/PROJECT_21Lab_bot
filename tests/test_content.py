from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from lab21_bot.models import (
    ContentItem,
    ContentKind,
    ContentStatus,
    StaffRole,
    User,
)
from lab21_bot.services.content import (
    choose_interviewee,
    content_is_silent,
    count_user_publications,
    moderate_content,
    record_channel_post,
    submit_community_content,
)


async def test_submit_story_keeps_photos_for_moderation(session: AsyncSession) -> None:
    from lab21_bot.services.content import submit_for_moderation

    author = User(telegram_id=5, full_name="Автор", is_approved=True)
    session.add(author)
    await session.flush()
    item = await submit_for_moderation(
        session,
        author,
        ContentKind.STORY,
        "Q: Что делал?\nA: Плата\n",
        "Q: Что делал?\nA: Плата\n",
        media=[
            {"type": "photo", "file_id": "photo-1"},
            {"type": "photo", "file_id": "photo-2"},
        ],
        llm_processed=False,
    )
    assert item.status is ContentStatus.MODERATION
    assert item.llm_processed is False
    assert len(item.media) == 2
    assert item.media[0]["file_id"] == "photo-1"

    author = User(telegram_id=1, full_name="Инженер", username="maker")
    watcher = User(telegram_id=2, full_name="Смотрящий", staff_role=StaffRole.WATCHER)
    session.add_all([author, watcher])
    await session.flush()

    item = await submit_community_content(
        session,
        author,
        ContentKind.STORY,
        "Собрал датчик, и он даже заработал.",
        [{"type": "photo", "file_id": "telegram-file"}],
    )
    assert item.status is ContentStatus.MODERATION
    assert item.source_text == "Собрал датчик, и он даже заработал."
    assert item.media[0]["file_id"] == "telegram-file"

    await moderate_content(
        session,
        watcher,
        item.id,
        ContentStatus.APPROVED,
        edited_text="Отредактированная история\n\n— Инженер (@maker)",
    )
    assert item.status is ContentStatus.APPROVED
    assert item.reviewer_id == watcher.telegram_id


async def test_channel_silence_and_interview_rotation(session: AsyncSession) -> None:
    now = datetime.now(UTC)
    channel_id = -100123
    first = User(telegram_id=10, full_name="Лорд", staff_role=StaffRole.LORD)
    second = User(telegram_id=20, full_name="Смотрящий", staff_role=StaffRole.WATCHER)
    session.add_all([first, second])
    await session.flush()

    assert await content_is_silent(session, channel_id, 3, now=now)
    await record_channel_post(
        session,
        channel_id,
        42,
        now=now - timedelta(days=4),
    )
    assert await content_is_silent(session, channel_id, 3, now=now)
    await record_channel_post(session, channel_id, 43, now=now)
    assert not await content_is_silent(session, channel_id, 3, now=now)

    selected_first = await choose_interviewee(session, channel_id, now=now)
    selected_second = await choose_interviewee(session, channel_id, now=now)
    assert selected_first is not None
    assert selected_second is not None
    assert selected_first.telegram_id != selected_second.telegram_id


async def test_count_user_publications_only_published(session: AsyncSession) -> None:
    author = User(telegram_id=50, full_name="Author", is_approved=True)
    other = User(telegram_id=51, full_name="Other", is_approved=True)
    session.add_all([author, other])
    await session.flush()
    session.add_all(
        [
            ContentItem(
                author_id=author.telegram_id,
                kind=ContentKind.STORY,
                status=ContentStatus.PUBLISHED,
                source_text="a",
                draft_text="a",
            ),
            ContentItem(
                author_id=author.telegram_id,
                kind=ContentKind.MEME,
                status=ContentStatus.PUBLISHED,
                source_text="b",
                draft_text="b",
            ),
            ContentItem(
                author_id=author.telegram_id,
                kind=ContentKind.STORY,
                status=ContentStatus.MODERATION,
                source_text="c",
                draft_text="c",
            ),
            ContentItem(
                author_id=other.telegram_id,
                kind=ContentKind.STORY,
                status=ContentStatus.PUBLISHED,
                source_text="d",
                draft_text="d",
            ),
        ]
    )
    await session.flush()
    assert await count_user_publications(session, author.telegram_id) == 2
