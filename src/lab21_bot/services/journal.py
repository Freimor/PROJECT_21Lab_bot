from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from lab21_bot.models import AdminAction, LedgerEntry, LedgerType, User

LEDGER_LABELS = {
    LedgerType.GRANT: "Начисление благодати",
    LedgerType.WITHDRAW: "Списание благодати",
    LedgerType.TRANSFER_OUT: "Перевод благодати (исходящий)",
    LedgerType.TRANSFER_IN: "Перевод благодати (входящий)",
    LedgerType.PURCHASE_RESERVE: "Резерв по заказу",
    LedgerType.PURCHASE_REFUND: "Возврат по заказу",
    LedgerType.ADJUSTMENT: "Корректировка",
    LedgerType.RESPECT_GRANT: "Начисление респекта",
    LedgerType.RESPECT_WITHDRAW: "Списание респекта",
}

ACTION_LABELS = {
    "set_staff_role": "Смена роли",
    "approve_join": "Заявка одобрена",
    "reject_join": "Заявка отклонена",
    "remove_member": "Удаление участника",
    "set_setting": "Изменение настройки",
    "request_restart": "Запрос перезагрузки",
    "create_product": "Товар создан",
    "update_product": "Товар изменён",
    "fulfill_order": "Заказ выдан",
    "cancel_order": "Заказ отменён",
}


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


async def recent_journal(session: AsyncSession, *, limit: int = 40) -> list[JournalEvent]:
    actions = list(
        await session.scalars(
            select(AdminAction).order_by(AdminAction.created_at.desc()).limit(limit)
        )
    )
    ledger = list(
        await session.scalars(
            select(LedgerEntry)
            .options(selectinload(LedgerEntry.account_user))
            .order_by(LedgerEntry.created_at.desc())
            .limit(limit)
        )
    )
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
        if action.details:
            bits.append(str(action.details))
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
