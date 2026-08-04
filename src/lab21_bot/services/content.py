from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from lab21_bot.models import (
    ChannelActivity,
    ContentItem,
    ContentKind,
    ContentStatus,
    Interview,
    StaffRole,
    User,
)
from lab21_bot.services.access import Permission, require_permission


class ContentError(RuntimeError):
    pass


async def create_staff_draft(
    session: AsyncSession,
    author: User,
    source_text: str,
    draft_text: str,
) -> ContentItem:
    require_permission(author, Permission.CREATE_STAFF_CONTENT)
    item = ContentItem(
        author_id=author.telegram_id,
        kind=ContentKind.STAFF_NOTE,
        status=ContentStatus.DRAFT,
        source_text=source_text.strip(),
        draft_text=draft_text.strip(),
    )
    session.add(item)
    await session.flush()
    return item


async def submit_community_content(
    session: AsyncSession,
    author: User,
    kind: ContentKind,
    text: str,
    media: list[dict[str, Any]] | None = None,
) -> ContentItem:
    if kind not in {ContentKind.STORY, ContentKind.MEME}:
        raise ContentError("Неверный тип пользовательского материала")
    signature = f"{author.full_name}" + (f" (@{author.username})" if author.username else "")
    item = ContentItem(
        author_id=author.telegram_id,
        kind=kind,
        status=ContentStatus.MODERATION,
        source_text=text.strip(),
        draft_text=f"{text.strip()}\n\n— {signature}",
        media=media or [],
    )
    session.add(item)
    await session.flush()
    return item


async def moderate_content(
    session: AsyncSession,
    reviewer: User,
    item_id: int,
    status: ContentStatus,
    *,
    edited_text: str | None = None,
    note: str | None = None,
) -> ContentItem:
    require_permission(reviewer, Permission.MODERATE_CONTENT)
    if status not in {
        ContentStatus.APPROVED,
        ContentStatus.REJECTED,
        ContentStatus.NEEDS_INFO,
    }:
        raise ContentError("Недопустимый результат модерации")
    item = await session.scalar(
        select(ContentItem).where(ContentItem.id == item_id).with_for_update()
    )
    if item is None or item.status in {ContentStatus.PUBLISHED, ContentStatus.REJECTED}:
        raise ContentError("Материал уже обработан или не существует")
    item.status = status
    item.reviewer_id = reviewer.telegram_id
    item.moderation_note = note
    if edited_text is not None:
        item.draft_text = edited_text.strip()
    await session.flush()
    return item


async def mark_published(
    session: AsyncSession,
    item_id: int,
    message_id: int,
    channel_id: int,
    *,
    now: datetime | None = None,
) -> ContentItem:
    now = now or datetime.now(UTC)
    item = await session.scalar(
        select(ContentItem).where(ContentItem.id == item_id).with_for_update()
    )
    if item is None:
        raise ContentError("Материал не найден")
    item.status = ContentStatus.PUBLISHED
    item.published_message_id = message_id
    item.published_at = now
    await record_channel_post(session, channel_id, message_id, now=now)
    return item


async def record_channel_post(
    session: AsyncSession,
    channel_id: int,
    message_id: int,
    *,
    now: datetime | None = None,
) -> ChannelActivity:
    now = now or datetime.now(UTC)
    activity = await session.get(ChannelActivity, channel_id)
    if activity is None:
        activity = ChannelActivity(
            channel_id=channel_id,
            last_post_at=now,
            last_message_id=message_id,
        )
        session.add(activity)
    else:
        activity.last_post_at = now
        activity.last_message_id = message_id
    return activity


async def content_is_silent(
    session: AsyncSession,
    channel_id: int,
    silence_days: int,
    *,
    now: datetime | None = None,
) -> bool:
    now = now or datetime.now(UTC)
    activity = await session.get(ChannelActivity, channel_id)
    if activity is None:
        return True
    last_post = activity.last_post_at
    if last_post.tzinfo is None:
        last_post = last_post.replace(tzinfo=UTC)
    return last_post <= now - timedelta(days=silence_days)


async def choose_interviewee(
    session: AsyncSession,
    channel_id: int,
    *,
    now: datetime | None = None,
) -> User | None:
    now = now or datetime.now(UTC)
    activity = await session.get(ChannelActivity, channel_id)
    last_id = activity.last_interviewee_id if activity else None
    staff = list(
        await session.scalars(
            select(User)
            .where(
                User.staff_role.in_([StaffRole.MAGISTER, StaffRole.TECH_PRIEST, StaffRole.WATCHER]),
                User.is_active.is_(True),
            )
            .order_by(User.telegram_id)
        )
    )
    active_interviewees = set(
        await session.scalars(
            select(Interview.employee_id).where(Interview.state.in_(["prompted", "generating"]))
        )
    )
    available_staff = [user for user in staff if user.telegram_id not in active_interviewees]
    if not available_staff:
        return None
    index = next(
        (
            position + 1
            for position, user in enumerate(available_staff)
            if user.telegram_id == last_id
        ),
        0,
    ) % len(available_staff)
    selected = available_staff[index]
    if activity is None:
        activity = ChannelActivity(
            channel_id=channel_id,
            last_post_at=now - timedelta(days=3650),
        )
        session.add(activity)
    activity.last_interviewee_id = selected.telegram_id
    activity.last_reminder_at = now
    session.add(Interview(employee_id=selected.telegram_id))
    return selected
