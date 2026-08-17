from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from lab21_bot.models import (
    AdminAction,
    ChannelActivity,
    ContentItem,
    ContentKind,
    ContentStatus,
    Interview,
    StaffRole,
    User,
)
from lab21_bot.services.access import Permission, require_permission
from lab21_bot.services.attribution import append_author_footer_html
from lab21_bot.services.destinations import DestinationError, destination_for_kind
from lab21_bot.services.economy import reward_post_publish
from lab21_bot.services.notify import TelegramSendError, send_telegram_message
from lab21_bot.services.telegram_html import normalize_telegram_html


class ContentError(RuntimeError):
    pass


KIND_LABELS = {
    ContentKind.IMPORTANT: "Важное",
    ContentKind.STORY: "Будни лабы",
    ContentKind.MEME: "Мем",
    ContentKind.STAFF_NOTE: "Черновик",
}


def channel_for_kind(settings: Any, kind: ContentKind) -> int:
    """Backward-compatible helper — chat id only."""
    try:
        return destination_for_kind(settings, kind).chat_id
    except DestinationError as exc:
        raise ContentError(str(exc)) from exc


async def submit_for_moderation(
    session: AsyncSession,
    author: User,
    kind: ContentKind,
    source_text: str,
    draft_text: str,
    media: list[dict[str, Any]] | None = None,
    *,
    llm_processed: bool | None = None,
) -> ContentItem:
    if kind not in {ContentKind.STORY, ContentKind.IMPORTANT, ContentKind.MEME}:
        raise ContentError("Неверный тип материала")
    if kind is ContentKind.IMPORTANT and author.staff_role not in {
        StaffRole.LORD,
        StaffRole.MAGISTER,
    }:
        raise ContentError("Важное могут предлагать только тёмный лорд и магистр")
    source = source_text.strip()
    draft = draft_text.strip()
    if not source:
        raise ContentError("Пустой исходный текст")
    if llm_processed is None:
        # Memes skip LLM; story/important start as raw source until first approval.
        llm_processed = kind is ContentKind.MEME
    item = ContentItem(
        author_id=author.telegram_id,
        kind=kind,
        status=ContentStatus.MODERATION,
        source_text=source,
        draft_text=draft or source,
        media=media or [],
        llm_processed=llm_processed,
    )
    session.add(item)
    await session.flush()
    return item


async def create_staff_draft(
    session: AsyncSession,
    author: User,
    source_text: str,
    draft_text: str,
    *,
    kind: ContentKind = ContentKind.STORY,
) -> ContentItem:
    require_permission(author, Permission.CREATE_STAFF_CONTENT)
    if kind not in {ContentKind.STORY, ContentKind.IMPORTANT}:
        raise ContentError("Служебный пост: Будни или Важное")
    return await submit_for_moderation(session, author, kind, source_text, draft_text)


async def submit_community_content(
    session: AsyncSession,
    author: User,
    kind: ContentKind,
    text: str,
    media: list[dict[str, Any]] | None = None,
    *,
    draft_text: str | None = None,
) -> ContentItem:
    if kind not in {ContentKind.STORY, ContentKind.MEME}:
        raise ContentError("Неверный тип пользовательского материала")
    signature = author.full_name
    source = text.strip()
    draft = (draft_text or source).strip()
    if kind is ContentKind.MEME and signature not in draft:
        from lab21_bot.services.attribution import author_title_for_user

        title = author_title_for_user(author)
        draft = (
            f"{draft}\n\n— {author.full_name} | {title}"
            if draft
            else f"— {author.full_name} | {title}"
        )
    return await submit_for_moderation(
        session,
        author,
        kind,
        source,
        draft,
        media=media,
    )


async def list_moderation_queue(
    session: AsyncSession,
    *,
    limit: int = 100,
    include_memes: bool = False,
) -> list[ContentItem]:
    query = (
        select(ContentItem)
        .options(selectinload(ContentItem.author))
        .where(ContentItem.status == ContentStatus.MODERATION)
        .order_by(ContentItem.created_at.asc())
        .limit(limit)
    )
    if not include_memes:
        query = query.where(ContentItem.kind != ContentKind.MEME)
    return list(await session.scalars(query))


async def list_scheduled(
    session: AsyncSession,
    *,
    limit: int = 50,
) -> list[ContentItem]:
    items = await session.scalars(
        select(ContentItem)
        .options(selectinload(ContentItem.author))
        .where(ContentItem.status == ContentStatus.SCHEDULED)
        .order_by(ContentItem.scheduled_at.asc())
        .limit(limit)
    )
    return list(items)


async def list_due_scheduled(
    session: AsyncSession,
    *,
    now: datetime | None = None,
) -> list[ContentItem]:
    now = now or datetime.now(UTC)
    items = await session.scalars(
        select(ContentItem)
        .options(selectinload(ContentItem.author))
        .where(
            ContentItem.status == ContentStatus.SCHEDULED,
            ContentItem.scheduled_at.is_not(None),
            ContentItem.scheduled_at <= now,
        )
        .order_by(ContentItem.scheduled_at.asc())
    )
    return list(items)


async def publication_stats(session: AsyncSession, lab_channel_id: int) -> dict[str, Any]:
    queue_counts: dict[str, int] = {}
    for kind in (ContentKind.STORY, ContentKind.IMPORTANT, ContentKind.MEME):
        queue_counts[kind.value] = int(
            await session.scalar(
                select(func.count())
                .select_from(ContentItem)
                .where(
                    ContentItem.status == ContentStatus.MODERATION,
                    ContentItem.kind == kind,
                )
            )
            or 0
        )
    scheduled_count = int(
        await session.scalar(
            select(func.count())
            .select_from(ContentItem)
            .where(ContentItem.status == ContentStatus.SCHEDULED)
        )
        or 0
    )
    activity = await session.get(ChannelActivity, lab_channel_id)
    silence_days: float | None = None
    if activity is not None:
        last = activity.last_post_at
        if last.tzinfo is None:
            last = last.replace(tzinfo=UTC)
        silence_days = round((datetime.now(UTC) - last).total_seconds() / 86400, 1)
    next_scheduled = await session.scalar(
        select(ContentItem)
        .where(ContentItem.status == ContentStatus.SCHEDULED)
        .order_by(ContentItem.scheduled_at.asc())
        .limit(1)
    )
    return {
        "queue_counts": queue_counts,
        "queue_total": queue_counts.get(ContentKind.STORY.value, 0)
        + queue_counts.get(ContentKind.IMPORTANT.value, 0),
        "queue_memes": queue_counts.get(ContentKind.MEME.value, 0),
        "scheduled_count": scheduled_count,
        "silence_days": silence_days,
        "next_scheduled_at": next_scheduled.scheduled_at if next_scheduled else None,
    }


_PUBLICATION_KINDS = (ContentKind.STORY, ContentKind.IMPORTANT, ContentKind.MEME)


async def count_user_publications(session: AsyncSession, user_id: int) -> int:
    value = await session.scalar(
        select(func.count())
        .select_from(ContentItem)
        .where(
            ContentItem.author_id == user_id,
            ContentItem.status == ContentStatus.PUBLISHED,
            ContentItem.kind.in_(_PUBLICATION_KINDS),
        )
    )
    return int(value or 0)


STATUS_LABELS = {
    ContentStatus.DRAFT: "Черновик",
    ContentStatus.MODERATION: "В очереди",
    ContentStatus.NEEDS_INFO: "Нужны правки",
    ContentStatus.APPROVED: "Одобрено",
    ContentStatus.SCHEDULED: "Запланировано",
    ContentStatus.REJECTED: "Отклонено",
    ContentStatus.PUBLISHED: "Опубликовано",
}


async def list_posts_journal(
    session: AsyncSession,
    *,
    status: ContentStatus | None = None,
    limit: int = 100,
) -> list[ContentItem]:
    query = (
        select(ContentItem)
        .options(selectinload(ContentItem.author))
        .where(ContentItem.kind.in_([ContentKind.STORY, ContentKind.IMPORTANT]))
        .order_by(ContentItem.created_at.desc())
        .limit(limit)
    )
    if status is not None:
        query = query.where(ContentItem.status == status)
    return list(await session.scalars(query))


async def reject_content(
    session: AsyncSession,
    reviewer: User,
    item_id: int,
    *,
    note: str | None = None,
) -> ContentItem:
    require_permission(reviewer, Permission.MODERATE_CONTENT)
    item = await session.scalar(
        select(ContentItem).where(ContentItem.id == item_id).with_for_update()
    )
    if item is None or item.status not in {
        ContentStatus.MODERATION,
        ContentStatus.SCHEDULED,
        ContentStatus.NEEDS_INFO,
    }:
        raise ContentError("Материал недоступен для отклонения")
    item.status = ContentStatus.REJECTED
    item.reviewer_id = reviewer.telegram_id
    item.moderation_note = note
    item.scheduled_at = None
    await session.flush()
    return item


async def update_draft_text(
    session: AsyncSession,
    reviewer: User,
    item_id: int,
    draft_text: str,
) -> ContentItem:
    require_permission(reviewer, Permission.MODERATE_CONTENT)
    item = await session.scalar(
        select(ContentItem).where(ContentItem.id == item_id).with_for_update()
    )
    if item is None or item.status not in {
        ContentStatus.MODERATION,
        ContentStatus.SCHEDULED,
    }:
        raise ContentError("Материал недоступен для правки")
    item.draft_text = draft_text.strip()
    item.reviewer_id = reviewer.telegram_id
    await session.flush()
    return item


async def schedule_content(
    session: AsyncSession,
    reviewer: User,
    item_id: int,
    scheduled_at: datetime,
    *,
    draft_text: str | None = None,
) -> ContentItem:
    require_permission(reviewer, Permission.MODERATE_CONTENT)
    if scheduled_at.tzinfo is None:
        scheduled_at = scheduled_at.replace(tzinfo=UTC)
    if scheduled_at <= datetime.now(UTC):
        raise ContentError("Время публикации должно быть в будущем")
    item = await session.scalar(
        select(ContentItem).where(ContentItem.id == item_id).with_for_update()
    )
    if item is None or item.status not in {
        ContentStatus.MODERATION,
        ContentStatus.SCHEDULED,
    }:
        raise ContentError("Материал недоступен для планирования")
    if item.kind in {ContentKind.STORY, ContentKind.IMPORTANT} and not item.llm_processed:
        raise ContentError("Сначала одобрите исходник для генерации LLM")
    if draft_text is not None:
        item.draft_text = draft_text.strip()
    item.status = ContentStatus.SCHEDULED
    item.scheduled_at = scheduled_at
    item.reviewer_id = reviewer.telegram_id
    await session.flush()
    return item


async def cancel_schedule(
    session: AsyncSession,
    reviewer: User,
    item_id: int,
) -> ContentItem:
    require_permission(reviewer, Permission.MODERATE_CONTENT)
    item = await session.scalar(
        select(ContentItem).where(ContentItem.id == item_id).with_for_update()
    )
    if item is None or item.status is not ContentStatus.SCHEDULED:
        raise ContentError("Нет запланированной публикации")
    item.status = ContentStatus.MODERATION
    item.scheduled_at = None
    item.reviewer_id = reviewer.telegram_id
    await session.flush()
    return item


async def publish_content_item(
    session: AsyncSession,
    bot_token: str,
    settings: Any,
    item_id: int,
    *,
    reviewer: User | None = None,
    draft_text: str | None = None,
    now: datetime | None = None,
) -> ContentItem:
    now = now or datetime.now(UTC)
    item = await session.scalar(
        select(ContentItem)
        .options(selectinload(ContentItem.author))
        .where(ContentItem.id == item_id)
        .with_for_update()
    )
    if item is None:
        raise ContentError("Материал не найден")
    if item.status not in {
        ContentStatus.MODERATION,
        ContentStatus.SCHEDULED,
        ContentStatus.APPROVED,
    }:
        raise ContentError("Материал нельзя опубликовать")
    if item.kind in {ContentKind.STORY, ContentKind.IMPORTANT} and not item.llm_processed:
        raise ContentError("Сначала одобрите исходник для генерации LLM")
    was_scheduled = item.status is ContentStatus.SCHEDULED
    if reviewer is not None:
        require_permission(reviewer, Permission.MODERATE_CONTENT)
        item.reviewer_id = reviewer.telegram_id
    if draft_text is not None:
        item.draft_text = draft_text.strip()
    text = (item.draft_text or item.source_text).strip()
    if item.kind in {ContentKind.STORY, ContentKind.IMPORTANT}:
        text = normalize_telegram_html(text)
        text = append_author_footer_html(text, item.author)
    if not text and not item.media:
        raise ContentError("Нечего публиковать")
    try:
        dest = destination_for_kind(settings, item.kind)
    except DestinationError as exc:
        raise ContentError(str(exc)) from exc
    try:
        message_id = await send_telegram_message(
            bot_token,
            dest.chat_id,
            text,
            media=item.media,
            message_thread_id=dest.thread_id,
            parse_mode=(
                "HTML"
                if item.kind in {ContentKind.STORY, ContentKind.IMPORTANT}
                else None
            ),
        )
    except TelegramSendError as exc:
        raise ContentError(str(exc)) from exc
    item.status = ContentStatus.PUBLISHED
    item.published_message_id = message_id
    item.published_channel_id = dest.chat_id
    item.published_at = now
    item.scheduled_at = None
    # Silence tracking is for «Будни» only (shared forum chat_id must not mix topics).
    if item.kind is ContentKind.STORY:
        await record_channel_post(session, settings.main_channel_id, message_id, now=now)
    actor_id = (
        reviewer.telegram_id
        if reviewer is not None
        else (item.reviewer_id or item.author_id)
    )
    session.add(
        AdminAction(
            actor_id=actor_id,
            action="publish_post",
            target_id=item.author_id,
            details={
                "item_id": item.id,
                "kind": item.kind.value,
                "kind_label": KIND_LABELS.get(item.kind, item.kind.value),
                "message_id": message_id,
                "scheduled": was_scheduled,
            },
        )
    )
    if item.kind in {ContentKind.STORY, ContentKind.IMPORTANT}:
        await reward_post_publish(session, item.id, item.author_id)
    await session.flush()
    return item


async def mark_llm_draft(
    session: AsyncSession,
    item_id: int,
    draft_text: str,
    *,
    reviewer: User | None = None,
) -> ContentItem:
    """Store LLM draft and return item to the second moderation stage."""
    item = await session.scalar(
        select(ContentItem).where(ContentItem.id == item_id).with_for_update()
    )
    if item is None:
        raise ContentError("Материал не найден")
    if item.kind not in {ContentKind.STORY, ContentKind.IMPORTANT}:
        raise ContentError("LLM только для Будней и Важного")
    if item.status not in {ContentStatus.MODERATION, ContentStatus.NEEDS_INFO}:
        raise ContentError("Материал недоступен для генерации")
    text = draft_text.strip()
    if not text:
        raise ContentError("LLM вернула пустой черновик")
    item.draft_text = normalize_telegram_html(text)
    item.llm_processed = True
    item.status = ContentStatus.MODERATION
    item.scheduled_at = None
    if reviewer is not None:
        item.reviewer_id = reviewer.telegram_id
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
    """Legacy helper used by bot callbacks."""
    require_permission(reviewer, Permission.MODERATE_CONTENT)
    if status is ContentStatus.REJECTED:
        return await reject_content(session, reviewer, item_id, note=note)
    if status is ContentStatus.NEEDS_INFO:
        item = await session.scalar(
            select(ContentItem).where(ContentItem.id == item_id).with_for_update()
        )
        if item is None:
            raise ContentError("Материал не найден")
        item.status = ContentStatus.NEEDS_INFO
        item.reviewer_id = reviewer.telegram_id
        item.moderation_note = note
        if edited_text is not None:
            item.draft_text = edited_text.strip()
        await session.flush()
        return item
    if status is ContentStatus.APPROVED:
        item = await session.scalar(
            select(ContentItem).where(ContentItem.id == item_id).with_for_update()
        )
        if item is None:
            raise ContentError("Материал не найден")
        if edited_text is not None:
            item.draft_text = edited_text.strip()
        item.status = ContentStatus.APPROVED
        item.reviewer_id = reviewer.telegram_id
        await session.flush()
        return item
    raise ContentError("Недопустимый результат модерации")


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
    item.published_channel_id = channel_id
    item.published_at = now
    item.scheduled_at = None
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
    """Legacy round-robin helper; silence reminders no longer auto-start interviews."""
    now = now or datetime.now(UTC)
    activity = await session.get(ChannelActivity, channel_id)
    last_id = activity.last_interviewee_id if activity else None
    staff = list(
        await session.scalars(
            select(User)
            .where(
                User.staff_role.in_(
                    [
                        StaffRole.LORD,
                        StaffRole.MAGISTER,
                        StaffRole.TECH_PRIEST,
                        StaffRole.WATCHER,
                    ]
                ),
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


def format_interview_source(answers: list[str], questions: tuple[str, ...]) -> str:
    lines: list[str] = []
    for index, answer in enumerate(answers):
        question = questions[index] if index < len(questions) else f"Вопрос {index + 1}"
        lines.append(f"Q: {question}\nA: {answer.strip()}")
    return "\n\n".join(lines)
