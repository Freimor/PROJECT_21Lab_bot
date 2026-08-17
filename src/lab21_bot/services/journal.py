from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from lab21_bot.data import phrases_data, skill_title
from lab21_bot.models import AdminAction, LedgerEntry, LedgerType, User

_PHRASES = phrases_data()
LEDGER_LABELS = {
    LedgerType(key): str(label) for key, label in _PHRASES["ledger"].items()
}
ACTION_LABELS = {key: str(label) for key, label in _PHRASES["admin_actions"].items()}


@dataclass(frozen=True, slots=True)
class JournalEvent:
    created_at: datetime
    title: str
    detail: str


def _name(user: User | None, fallback: str | int | None) -> str:
    if user is not None:
        if user.username:
            return f"{user.full_name} (@{user.username})"
        return user.full_name
    if fallback is None:
        return "—"
    return str(fallback)


def _format_action_details(action: str, details: dict) -> list[str]:
    bits: list[str] = []
    kind_label = details.get("kind_label")
    if kind_label:
        bits.append(str(kind_label))
    elif details.get("kind"):
        bits.append(str(details["kind"]))
    skills = details.get("skills")
    if isinstance(skills, list) and skills:
        titles = ", ".join(skill_title(str(skill_id)) for skill_id in skills)
        bits.append(f"навыки: {titles}")
    if details.get("item_id") is not None:
        bits.append(f"пост #{details['item_id']}")
    if details.get("template_id") is not None:
        bits.append(f"шаблон #{details['template_id']}")
    if details.get("application_id") is not None and action.endswith("join"):
        bits.append(f"заявка #{details['application_id']}")
    if details.get("application_id") is not None and "skill_validation" in action:
        bits.append(f"заявка #{details['application_id']}")
    if details.get("scheduled") is True:
        bits.append("по расписанию")
    note = details.get("note")
    if note:
        bits.append(str(note))
    if not bits and details:
        bits.append(
            " · ".join(f"{key}={value}" for key, value in details.items() if value is not None)
        )
    return bits


async def recent_journal(
    session: AsyncSession,
    *,
    limit: int = 40,
    since: datetime | None = None,
    until: datetime | None = None,
) -> list[JournalEvent]:
    action_query = select(AdminAction).order_by(AdminAction.created_at.desc()).limit(limit * 2)
    ledger_query = (
        select(LedgerEntry)
        .options(selectinload(LedgerEntry.account_user))
        .order_by(LedgerEntry.created_at.desc())
        .limit(limit * 2)
    )
    if since is not None:
        action_query = action_query.where(AdminAction.created_at >= since)
        ledger_query = ledger_query.where(LedgerEntry.created_at >= since)
    if until is not None:
        action_query = action_query.where(AdminAction.created_at <= until)
        ledger_query = ledger_query.where(LedgerEntry.created_at <= until)

    actions = list(await session.scalars(action_query))
    ledger = list(await session.scalars(ledger_query))
    user_ids = {item.actor_id for item in actions} | {
        item.target_id for item in actions if item.target_id is not None
    }
    users = {
        user.telegram_id: user
        for user in await session.scalars(select(User).where(User.telegram_id.in_(user_ids or {0})))
    }

    events: list[JournalEvent] = []
    for action in actions:
        title = ACTION_LABELS.get(action.action, action.action)
        actor = _name(users.get(action.actor_id), action.actor_id)
        target = (
            _name(users.get(action.target_id), action.target_id)
            if action.target_id is not None
            else None
        )
        bits = [f"кто: {actor}"]
        if target:
            bits.append(f"кого: {target}")
        detail_bits = _format_action_details(action.action, action.details or {})
        if detail_bits:
            bits.extend(detail_bits)
        events.append(
            JournalEvent(created_at=action.created_at, title=title, detail=" · ".join(bits))
        )

    for entry in ledger:
        title = LEDGER_LABELS.get(entry.entry_type, entry.entry_type.value)
        account = _name(entry.account_user, entry.account_user_id)
        events.append(
            JournalEvent(
                created_at=entry.created_at,
                title=title,
                detail=(
                    f"{account}: {entry.delta:+d} → {entry.balance_after}"
                    + (f" · {entry.reason}" if entry.reason else "")
                ),
            )
        )

    events.sort(key=lambda item: item.created_at, reverse=True)
    return events[:limit]
