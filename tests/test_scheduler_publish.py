from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lab21_bot.config import Settings
from lab21_bot.models import ContentItem, ContentKind, ContentStatus, User
from lab21_bot.scheduler import create_scheduler


def _settings() -> Settings:
    return Settings(  # type: ignore[arg-type]
        telegram_bot_token=SecretStr("1:test"),
        bootstrap_magister_id=1,
        database_url="sqlite+aiosqlite:///:memory:",
        main_channel_id=-1001,
        staff_chat_id=-1002,
        timezone="UTC",
    )


@pytest.mark.asyncio
async def test_publish_due_logs_failures(
    session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    author = User(telegram_id=7, full_name="Author", is_approved=True)
    session.add(author)
    await session.flush()
    due = ContentItem(
        author_id=author.telegram_id,
        kind=ContentKind.MEME,
        status=ContentStatus.SCHEDULED,
        source_text="meme",
        draft_text="meme",
        media=[],
        scheduled_at=datetime.now(UTC) - timedelta(minutes=1),
    )
    session.add(due)
    await session.commit()

    factory = async_sessionmaker(session.bind, expire_on_commit=False)
    settings = _settings()

    async def boom(*_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError("publish exploded")

    monkeypatch.setattr("lab21_bot.scheduler.publish_content_item", boom)

    logged: list[dict[str, Any]] = []

    class FakeLogger:
        def exception(self, event: str, **kwargs: Any) -> None:
            logged.append({"event": event, **kwargs})

    monkeypatch.setattr("lab21_bot.scheduler.logger", FakeLogger())

    class DummyBot:
        pass

    scheduler = create_scheduler(DummyBot(), settings, factory)  # type: ignore[arg-type]
    job = scheduler.get_job("publish-due-content")
    assert job is not None
    await job.func()
    assert logged
    assert logged[0]["event"] == "publish_due_failed"
    assert logged[0]["item_id"] == due.id
