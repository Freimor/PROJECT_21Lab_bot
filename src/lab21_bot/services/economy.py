from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import cast

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from lab21_bot.models import CommunityRank, LedgerEntry, LedgerType, User
from lab21_bot.services.access import Permission, require_permission


class EconomyError(RuntimeError):
    pass


def _validate(amount: int, reason: str) -> str:
    if amount <= 0:
        raise EconomyError("Сумма должна быть положительной")
    normalized_reason = reason.strip()
    if not normalized_reason:
        raise EconomyError("Причина обязательна")
    if len(normalized_reason) > 500:
        raise EconomyError("Причина слишком длинная")
    return normalized_reason


async def _locked_user(session: AsyncSession, telegram_id: int) -> User:
    user = await session.scalar(
        select(User).where(User.telegram_id == telegram_id).with_for_update()
    )
    if user is None:
        raise EconomyError("Участник не зарегистрирован в боте")
    return user


async def _existing_entry(session: AsyncSession, idempotency_key: str | None) -> LedgerEntry | None:
    if not idempotency_key:
        return None
    return cast(
        LedgerEntry | None,
        await session.scalar(
            select(LedgerEntry).where(LedgerEntry.idempotency_key == idempotency_key)
        ),
    )


def _require_participant(user: User) -> None:
    if user.staff_role is not None:
        raise EconomyError("У сотрудников нет благодати и респекта")


async def change_balance(
    session: AsyncSession,
    actor: User,
    target_id: int,
    amount: int,
    reason: str,
    *,
    grant: bool,
    idempotency_key: str | None = None,
) -> LedgerEntry:
    require_permission(actor, Permission.MANAGE_ECONOMY)
    reason = _validate(amount, reason)
    existing = await _existing_entry(session, idempotency_key)
    if existing:
        return existing

    target = await _locked_user(session, target_id)
    _require_participant(target)
    delta = amount if grant else -amount
    if target.balance + delta < 0:
        raise EconomyError("Недостаточно благодати")
    target.balance += delta
    entry = LedgerEntry(
        transaction_group=str(uuid.uuid4()),
        idempotency_key=idempotency_key,
        initiator_id=actor.telegram_id,
        account_user_id=target.telegram_id,
        delta=delta,
        balance_after=target.balance,
        entry_type=LedgerType.GRANT if grant else LedgerType.WITHDRAW,
        reason=reason,
    )
    session.add(entry)
    await session.flush()
    return entry


async def change_respect(
    session: AsyncSession,
    actor: User,
    target_id: int,
    amount: int,
    reason: str,
    *,
    grant: bool,
    idempotency_key: str | None = None,
) -> LedgerEntry:
    require_permission(actor, Permission.MANAGE_ECONOMY)
    reason = _validate(amount, reason)
    existing = await _existing_entry(session, idempotency_key)
    if existing:
        return existing

    target = await _locked_user(session, target_id)
    _require_participant(target)
    delta = amount if grant else -amount
    if target.respect + delta < 0:
        raise EconomyError("Недостаточно респекта")
    target.respect += delta
    entry = LedgerEntry(
        transaction_group=str(uuid.uuid4()),
        idempotency_key=idempotency_key,
        initiator_id=actor.telegram_id,
        account_user_id=target.telegram_id,
        delta=delta,
        balance_after=target.respect,
        entry_type=LedgerType.RESPECT_GRANT if grant else LedgerType.RESPECT_WITHDRAW,
        reason=reason,
    )
    session.add(entry)
    await session.flush()
    return entry


async def transfer(
    session: AsyncSession,
    sender_id: int,
    recipient_id: int,
    amount: int,
    reason: str,
    daily_limit: int,
    *,
    idempotency_key: str,
    now: datetime | None = None,
) -> tuple[LedgerEntry, LedgerEntry]:
    reason = _validate(amount, reason)
    if sender_id == recipient_id:
        raise EconomyError("Нельзя переводить благодать самому себе")
    existing = await _existing_entry(session, f"{idempotency_key}:out")
    if existing:
        incoming = await session.scalar(
            select(LedgerEntry).where(LedgerEntry.idempotency_key == f"{idempotency_key}:in")
        )
        if incoming is None:
            raise EconomyError("Обнаружена незавершённая транзакция")
        return existing, incoming

    first_id, second_id = sorted((sender_id, recipient_id))
    first = await _locked_user(session, first_id)
    second = await _locked_user(session, second_id)
    sender = first if first.telegram_id == sender_id else second
    recipient = second if second.telegram_id == recipient_id else first

    if sender.rank is not CommunityRank.ADEPT or recipient.rank is not CommunityRank.ADEPT:
        raise EconomyError("Переводы доступны только между Адептами")
    _require_participant(sender)
    _require_participant(recipient)
    if sender.balance < amount:
        raise EconomyError("Недостаточно благодати")

    now = now or datetime.now(UTC)
    if daily_limit > 0:
        start = now - timedelta(hours=24)
        transferred = await session.scalar(
            select(func.coalesce(func.sum(-LedgerEntry.delta), 0)).where(
                LedgerEntry.account_user_id == sender_id,
                LedgerEntry.entry_type == LedgerType.TRANSFER_OUT,
                LedgerEntry.created_at >= start,
            )
        )
        if int(transferred or 0) + amount > daily_limit:
            raise EconomyError(f"Превышен суточный лимит {daily_limit} благодати")

    sender.balance -= amount
    recipient.balance += amount
    group = str(uuid.uuid4())
    outgoing = LedgerEntry(
        transaction_group=group,
        idempotency_key=f"{idempotency_key}:out",
        initiator_id=sender_id,
        account_user_id=sender_id,
        counterparty_id=recipient_id,
        delta=-amount,
        balance_after=sender.balance,
        entry_type=LedgerType.TRANSFER_OUT,
        reason=reason,
        created_at=now,
    )
    incoming = LedgerEntry(
        transaction_group=group,
        idempotency_key=f"{idempotency_key}:in",
        initiator_id=sender_id,
        account_user_id=recipient_id,
        counterparty_id=sender_id,
        delta=amount,
        balance_after=recipient.balance,
        entry_type=LedgerType.TRANSFER_IN,
        reason=reason,
        created_at=now,
    )
    session.add_all([outgoing, incoming])
    await session.flush()
    return outgoing, incoming


async def history(session: AsyncSession, user_id: int, limit: int = 20) -> list[LedgerEntry]:
    rows = await session.scalars(
        select(LedgerEntry)
        .where(LedgerEntry.account_user_id == user_id)
        .order_by(LedgerEntry.created_at.desc(), LedgerEntry.id.desc())
        .limit(limit)
    )
    return list(rows)
