from __future__ import annotations

import html
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from lab21_bot.data import phrase
from lab21_bot.models import (
    AdminAction,
    ContentItem,
    ContentKind,
    ContentStatus,
    ContentTemplate,
    TemplateKind,
    User,
)
from lab21_bot.services.access import Permission, require_permission
from lab21_bot.services.attribution import (
    format_author_footer_for_user,
    format_author_footer_html,
    strip_author_signature,
)
from lab21_bot.services.economy import reward_meme_approve
from lab21_bot.services.templates import meme_title_from_text


class MemeError(RuntimeError):
    pass


_PHOTO_PLACEHOLDER = "(фото)"
_GIF_PLACEHOLDER = "(gif)"

# Back-compat alias
strip_meme_signature = strip_author_signature


def _is_media_placeholder(body: str) -> bool:
    folded = body.casefold()
    return folded in {_PHOTO_PLACEHOLDER, _GIF_PLACEHOLDER}


def format_meme_post_html(
    text: str,
    *,
    author_name: str | None = None,
    author_username: str | None = None,
    author_title: str | None = None,
    author: User | None = None,
) -> str:
    """Format meme body as Telegram HTML blockquote + italic attribution.

    Media-only memes (empty body or ``(фото)`` / ``(GIF)`` placeholders) get
    attribution only — no empty/placeholder blockquote.
    """
    body = strip_author_signature(text)
    lines: list[str] = []
    if body and not _is_media_placeholder(body):
        lines.append(f"<blockquote>{html.escape(body)}</blockquote>")
    if author is not None:
        lines.append(format_author_footer_for_user(author))
    else:
        lines.append(
            format_author_footer_html(
                author_name=author_name,
                author_username=author_username,
                title=author_title,
            )
        )
    return "\n".join(lines)


def meme_post_html_from_template(template: ContentTemplate) -> str:
    author = template.author
    if author is None:
        return format_meme_post_html(template.body, author_name="System")
    return format_meme_post_html(template.body, author=author)


async def list_meme_applications(
    session: AsyncSession,
    *,
    limit: int = 100,
) -> list[ContentItem]:
    return list(
        await session.scalars(
            select(ContentItem)
            .options(selectinload(ContentItem.author))
            .where(
                ContentItem.kind == ContentKind.MEME,
                ContentItem.status == ContentStatus.MODERATION,
            )
            .order_by(ContentItem.created_at.asc())
            .limit(limit)
        )
    )


async def approve_meme_to_collection(
    session: AsyncSession,
    reviewer: User,
    item_id: int,
    *,
    title: str | None = None,
    collection_key: str | None = None,
) -> tuple[ContentItem, ContentTemplate]:
    require_permission(reviewer, Permission.MODERATE_CONTENT)
    item = await session.scalar(
        select(ContentItem)
        .options(selectinload(ContentItem.author))
        .where(ContentItem.id == item_id)
        .with_for_update()
    )
    if item is None or item.kind is not ContentKind.MEME:
        raise MemeError("Заявка на мем не найдена")
    if item.status is not ContentStatus.MODERATION:
        raise MemeError("Заявка уже обработана")

    body = strip_meme_signature((item.draft_text or item.source_text).strip())
    if not body and not item.media:
        raise MemeError("Пустой мем")
    if not body:
        body = "(фото)"

    label = (title or "").strip() or meme_title_from_text(item.source_text)
    key = (collection_key or "").strip() or None
    if not key:
        key = "default"
        try:
            from lab21_bot.services.seasons import active_season

            season = await active_season(session)
            if season is not None and season.meme_collection:
                key = season.meme_collection
        except Exception:
            key = "default"
    template = ContentTemplate(
        kind=TemplateKind.MEME,
        title=label[:160],
        body=body,
        media=list(item.media or []),
        collection_key=key,
        author_id=item.author_id,
        is_active=True,
        reaction_count=0,
    )
    session.add(template)
    await session.flush()

    item.status = ContentStatus.APPROVED
    item.reviewer_id = reviewer.telegram_id
    item.template_id = template.id
    item.published_at = None

    author = await session.scalar(
        select(User).where(User.telegram_id == item.author_id).with_for_update()
    )
    if author is not None:
        author.approved_meme_count += 1

    session.add(
        AdminAction(
            actor_id=reviewer.telegram_id,
            action="approve_meme",
            target_id=item.author_id,
            details={"item_id": item.id, "template_id": template.id, "collection_key": key},
        )
    )
    await reward_meme_approve(session, item.id, item.author_id)
    await session.flush()
    return item, template


async def reject_meme_application(
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
    if item is None or item.kind is not ContentKind.MEME:
        raise MemeError("Заявка на мем не найдена")
    if item.status is not ContentStatus.MODERATION:
        raise MemeError("Заявка уже обработана")
    item.status = ContentStatus.REJECTED
    item.reviewer_id = reviewer.telegram_id
    item.moderation_note = note
    session.add(
        AdminAction(
            actor_id=reviewer.telegram_id,
            action="reject_meme",
            target_id=item.author_id,
            details={"item_id": item.id, "note": note},
        )
    )
    await session.flush()
    return item


def message_meme_approved() -> str:
    return phrase("memes", "approved")


def message_meme_rejected(*, note: str | None = None, reviewer: User | None = None) -> str:
    from lab21_bot.services.attribution import append_author_footer_html

    text = (note or "").strip()
    body = text if text else phrase("memes", "rejected")
    safe = html.escape(body)
    if reviewer is None:
        return safe
    return append_author_footer_html(safe, reviewer)


async def record_collection_meme_post(
    session: AsyncSession,
    template: ContentTemplate,
    *,
    chat_id: int,
    message_id: int,
    fallback_author_id: int,
    now: datetime | None = None,
) -> ContentItem:
    """Create a published ContentItem for a collection meme so reactions are tracked."""
    now = now or datetime.now(UTC)
    author_id = template.author_id or fallback_author_id
    item = ContentItem(
        author_id=author_id,
        kind=ContentKind.MEME,
        status=ContentStatus.PUBLISHED,
        source_text=template.body,
        draft_text=template.body,
        media=list(template.media or []),
        published_channel_id=chat_id,
        published_message_id=message_id,
        published_at=now,
        template_id=template.id,
        reaction_count=0,
    )
    session.add(item)
    await session.flush()
    return item


async def post_collection_meme_now(
    session: AsyncSession,
    actor: User,
    template_id: int,
    *,
    bot_token: str,
    chat_id: int,
    message_thread_id: int | None,
    fallback_author_id: int,
) -> ContentItem:
    """Manually post a collection meme to the flood destination."""
    require_permission(actor, Permission.MANAGE_SETTINGS)
    template = await session.scalar(
        select(ContentTemplate)
        .options(selectinload(ContentTemplate.author))
        .where(ContentTemplate.id == template_id)
    )
    if template is None or template.kind is not TemplateKind.MEME:
        raise MemeError("Мем в коллекции не найден")
    if not template.is_active:
        raise MemeError("Мем выключен")
    from lab21_bot.services.notify import TelegramSendError, send_telegram_message

    try:
        message_id = await send_telegram_message(
            bot_token,
            chat_id,
            meme_post_html_from_template(template),
            media=list(template.media or []) or None,
            message_thread_id=message_thread_id,
            parse_mode="HTML",
        )
    except TelegramSendError as exc:
        raise MemeError(str(exc)) from exc
    item = await record_collection_meme_post(
        session,
        template,
        chat_id=chat_id,
        message_id=message_id,
        fallback_author_id=fallback_author_id,
    )
    session.add(
        AdminAction(
            actor_id=actor.telegram_id,
            action="post_meme_now",
            target_id=template.author_id,
            details={"template_id": template.id, "item_id": item.id},
        )
    )
    await session.flush()
    return item
