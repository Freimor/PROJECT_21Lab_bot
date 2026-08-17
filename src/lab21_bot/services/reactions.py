from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from lab21_bot.models import (
    ContentItem,
    ContentKind,
    ContentStatus,
    ContentTemplate,
    LedgerEntry,
    LedgerType,
    User,
)

# Участниковые посты, опубликованные через бота.
_REACTION_KINDS = frozenset({ContentKind.STORY, ContentKind.MEME})


async def _published_item(
    session: AsyncSession,
    *,
    chat_id: int,
    message_id: int,
) -> ContentItem | None:
    return await session.scalar(
        select(ContentItem)
        .where(
            ContentItem.published_channel_id == chat_id,
            ContentItem.published_message_id == message_id,
            ContentItem.status == ContentStatus.PUBLISHED,
            ContentItem.kind.in_(_REACTION_KINDS),
        )
        .with_for_update()
    )


async def _sync_template_reactions(session: AsyncSession, item: ContentItem) -> None:
    if item.template_id is None:
        return
    template = await session.get(ContentTemplate, item.template_id, with_for_update=True)
    if template is None:
        return
    total = int(
        await session.scalar(
            select(func.coalesce(func.sum(ContentItem.reaction_count), 0)).where(
                ContentItem.template_id == template.id,
                ContentItem.status == ContentStatus.PUBLISHED,
            )
        )
        or 0
    )
    template.reaction_count = total


async def _apply_reaction_total(
    session: AsyncSession,
    item: ContentItem,
    total_reactions: int,
) -> LedgerEntry | None:
    total = max(0, total_reactions)
    previous = item.reaction_count
    if total == previous:
        return None

    author = await session.scalar(
        select(User).where(User.telegram_id == item.author_id).with_for_update()
    )
    item.reaction_count = total
    await _sync_template_reactions(session, item)
    if author is None or author.staff_role is not None or not author.is_approved:
        return None

    delta = total - previous
    if delta == 0:
        return None
    if delta < 0 and author.respect + delta < 0:
        delta = -author.respect
        if delta == 0:
            return None

    author.respect += delta
    entry = LedgerEntry(
        transaction_group=str(uuid.uuid4()),
        idempotency_key=f"post-reaction:{item.id}:from:{previous}:to:{total}",
        initiator_id=None,
        account_user_id=author.telegram_id,
        delta=delta,
        balance_after=author.respect,
        entry_type=LedgerType.RESPECT_GRANT if delta > 0 else LedgerType.RESPECT_WITHDRAW,
        reason=f"Реакции на пост #{item.id}",
    )
    session.add(entry)
    await session.flush()
    return entry


async def sync_post_reaction_total(
    session: AsyncSession,
    *,
    chat_id: int,
    message_id: int,
    total_reactions: int,
) -> LedgerEntry | None:
    """Выставить абсолютное число реакций (каналы / anonymous count updates)."""
    item = await _published_item(session, chat_id=chat_id, message_id=message_id)
    if item is None:
        return None
    return await _apply_reaction_total(session, item, total_reactions)


async def apply_post_reaction_delta(
    session: AsyncSession,
    *,
    chat_id: int,
    message_id: int,
    delta: int,
) -> LedgerEntry | None:
    """Сдвинуть счётчик на delta (группы с именными реакциями)."""
    if delta == 0:
        return None
    item = await _published_item(session, chat_id=chat_id, message_id=message_id)
    if item is None:
        return None
    return await _apply_reaction_total(session, item, item.reaction_count + delta)
