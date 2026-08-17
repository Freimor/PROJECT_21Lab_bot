"""Intake and moderation for /bug and /upgrade reports."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from lab21_bot.models import (
    AdminAction,
    FeedbackKind,
    FeedbackReport,
    FeedbackStatus,
    User,
)
from lab21_bot.services.access import Permission, require_permission

_BUG_RE = re.compile(r"(?i)(?:^|\s)/bug(?:@\w+)?(?=\s|$)")
_UPGRADE_RE = re.compile(r"(?i)(?:^|\s)/upgrade(?:@\w+)?(?=\s|$)")
_CMD_STRIP = re.compile(r"(?i)(?:^|\s)/(?:bug|upgrade)(?:@\w+)?")

REACTION_PENDING = "🤔"
REACTION_ACCEPTED = "✅"
REACTION_REJECTED = "❌"

KIND_LABELS = {
    FeedbackKind.BUG: "Баг",
    FeedbackKind.UPGRADE: "Предложение",
}


class FeedbackError(RuntimeError):
    pass


def detect_feedback_kind(text: str | None) -> FeedbackKind | None:
    raw = text or ""
    has_bug = bool(_BUG_RE.search(raw))
    has_upgrade = bool(_UPGRADE_RE.search(raw))
    if has_bug and not has_upgrade:
        return FeedbackKind.BUG
    if has_upgrade and not has_bug:
        return FeedbackKind.UPGRADE
    return None


def clean_feedback_text(text: str | None) -> str:
    cleaned = _CMD_STRIP.sub(" ", text or "")
    return re.sub(r"[ \t]{2,}", " ", cleaned).strip()


def media_from_telegram_message(message: Any) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    if getattr(message, "photo", None):
        items.append({"type": "photo", "file_id": message.photo[-1].file_id})
    if getattr(message, "video", None):
        items.append({"type": "video", "file_id": message.video.file_id})
    if getattr(message, "animation", None):
        items.append({"type": "animation", "file_id": message.animation.file_id})
    if getattr(message, "document", None):
        doc = message.document
        mime = (doc.mime_type or "").lower()
        if mime.startswith("video/") or mime.startswith("image/"):
            items.append(
                {
                    "type": "video" if mime.startswith("video/") else "document",
                    "file_id": doc.file_id,
                }
            )
    return items


async def create_feedback_report(
    session: AsyncSession,
    *,
    kind: FeedbackKind,
    chat_id: int,
    message_id: int,
    message_thread_id: int | None,
    text: str,
    media: list[dict[str, Any]],
    author: User | None,
    author_name: str,
    author_username: str | None,
) -> FeedbackReport | None:
    existing = await session.scalar(
        select(FeedbackReport).where(
            FeedbackReport.chat_id == chat_id,
            FeedbackReport.message_id == message_id,
        )
    )
    if existing is not None:
        return None
    row = FeedbackReport(
        kind=kind,
        status=FeedbackStatus.PENDING,
        author_id=author.telegram_id if author else None,
        author_name=author_name[:200],
        author_username=author_username,
        chat_id=chat_id,
        message_id=message_id,
        message_thread_id=message_thread_id,
        text=text,
        media=media,
    )
    session.add(row)
    await session.flush()
    return row


async def list_feedback(
    session: AsyncSession,
    *,
    kind: FeedbackKind | None = None,
    status: FeedbackStatus | None = FeedbackStatus.PENDING,
    limit: int = 100,
) -> list[FeedbackReport]:
    stmt = select(FeedbackReport).order_by(FeedbackReport.id.desc()).limit(limit)
    if kind is not None:
        stmt = stmt.where(FeedbackReport.kind == kind)
    if status is not None:
        stmt = stmt.where(FeedbackReport.status == status)
    return list(await session.scalars(stmt))


async def count_pending_feedback(session: AsyncSession) -> tuple[int, int]:
    bugs = await session.scalar(
        select(func.count())
        .select_from(FeedbackReport)
        .where(
            FeedbackReport.status == FeedbackStatus.PENDING,
            FeedbackReport.kind == FeedbackKind.BUG,
        )
    )
    upgrades = await session.scalar(
        select(func.count())
        .select_from(FeedbackReport)
        .where(
            FeedbackReport.status == FeedbackStatus.PENDING,
            FeedbackReport.kind == FeedbackKind.UPGRADE,
        )
    )
    return int(bugs or 0), int(upgrades or 0)


async def decide_feedback(
    session: AsyncSession,
    actor: User,
    report_id: int,
    *,
    accept: bool,
    note: str | None = None,
) -> FeedbackReport:
    require_permission(actor, Permission.MODERATE_CONTENT)
    row = await session.get(FeedbackReport, report_id)
    if row is None:
        raise FeedbackError("Заявка не найдена")
    if row.status is not FeedbackStatus.PENDING:
        raise FeedbackError("Заявка уже обработана")
    row.status = FeedbackStatus.ACCEPTED if accept else FeedbackStatus.REJECTED
    row.decided_by = actor.telegram_id
    row.decided_at = datetime.now(UTC)
    row.decision_note = (note or "").strip() or None
    session.add(
        AdminAction(
            actor_id=actor.telegram_id,
            action="feedback_accept" if accept else "feedback_reject",
            target_id=row.id,
            details={"kind": row.kind.value, "note": row.decision_note},
        )
    )
    await session.flush()
    return row
