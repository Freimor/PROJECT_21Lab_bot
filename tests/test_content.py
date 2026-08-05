from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from lab21_bot.models import (
    ContentKind,
    ContentStatus,
    StaffRole,
    User,
)
from lab21_bot.services.content import (
    choose_interviewee,
    content_is_silent,
    moderate_content,
    record_channel_post,
    submit_community_content,
)


async def test_community_content_is_attributed_and_moderated(
    session: AsyncSession,
) -> None:
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
    assert "Инженер (@maker)" in (item.draft_text or "")
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
