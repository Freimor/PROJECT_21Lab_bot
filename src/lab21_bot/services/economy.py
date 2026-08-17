from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import cast

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from lab21_bot.data import rank_base_grace, rank_can_transfer
from lab21_bot.models import LedgerEntry, LedgerType, User
from lab21_bot.services.access import Permission, require_permission


class EconomyError(RuntimeError):
    pass


# Награды за контент (фиксированные механики Lab21).
POST_PUBLISH_GRACE = 20
POST_PUBLISH_RESPECT = 5
MEME_APPROVE_GRACE = 5
MEME_APPROVE_RESPECT = 1


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
        raise EconomyError("У сотрудников нет 🙏 и ❇")


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
        raise EconomyError("Недостаточно 🙏")
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
        raise EconomyError("Недостаточно ❇")
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
        raise EconomyError("Нельзя переводить 🙏 самому себе")
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

    if not rank_can_transfer(str(sender.rank)) or not rank_can_transfer(str(recipient.rank)):
        raise EconomyError("Переводы доступны только между Адептами")
    _require_participant(sender)
    _require_participant(recipient)
    if sender.balance < amount:
        raise EconomyError("Недостаточно 🙏")
    base = rank_base_grace(str(sender.rank))
    if sender.balance - amount < base:
        raise EconomyError(
            f"Нельзя опустить баланс ниже базовой 🙏 ранга ({base}). "
            f"Доступно к переводу: {max(0, sender.balance - base)}"
        )

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
            raise EconomyError(f"Превышен суточный лимит {daily_limit} 🙏")

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


async def reward_participant(
    session: AsyncSession,
    user_id: int,
    *,
    grace: int,
    respect: int,
    reason: str,
    idempotency_key: str,
    grace_entry_type: LedgerType = LedgerType.GRANT,
) -> tuple[LedgerEntry | None, LedgerEntry | None]:
    """Начислить 🙏 и/или ❇ участнику (не staff). Идемпотентно."""
    if grace < 0 or respect < 0:
        raise EconomyError("Награда не может быть отрицательной")
    if grace == 0 and respect == 0:
        return None, None

    existing_grace = await _existing_entry(session, f"{idempotency_key}:grace")
    existing_respect = await _existing_entry(session, f"{idempotency_key}:respect")
    if (grace == 0 or existing_grace is not None) and (
        respect == 0 or existing_respect is not None
    ):
        return existing_grace, existing_respect

    user = await _locked_user(session, user_id)
    if user.staff_role is not None or not user.is_approved:
        return None, None

    group = str(uuid.uuid4())
    grace_entry = existing_grace
    respect_entry = existing_respect
    if grace > 0 and grace_entry is None:
        user.balance += grace
        grace_entry = LedgerEntry(
            transaction_group=group,
            idempotency_key=f"{idempotency_key}:grace",
            initiator_id=None,
            account_user_id=user.telegram_id,
            delta=grace,
            balance_after=user.balance,
            entry_type=grace_entry_type,
            reason=reason,
        )
        session.add(grace_entry)
    if respect > 0 and respect_entry is None:
        user.respect += respect
        respect_entry = LedgerEntry(
            transaction_group=group,
            idempotency_key=f"{idempotency_key}:respect",
            initiator_id=None,
            account_user_id=user.telegram_id,
            delta=respect,
            balance_after=user.respect,
            entry_type=LedgerType.RESPECT_GRANT,
            reason=reason,
        )
        session.add(respect_entry)
    await session.flush()
    return grace_entry, respect_entry


async def reward_post_publish(session: AsyncSession, item_id: int, author_id: int) -> None:
    await reward_participant(
        session,
        author_id,
        grace=POST_PUBLISH_GRACE,
        respect=POST_PUBLISH_RESPECT,
        reason=f"Награда за опубликованный пост #{item_id}",
        idempotency_key=f"post-reward:{item_id}",
        grace_entry_type=LedgerType.POST_REWARD,
    )


async def reward_meme_approve(session: AsyncSession, item_id: int, author_id: int) -> None:
    await reward_participant(
        session,
        author_id,
        grace=MEME_APPROVE_GRACE,
        respect=MEME_APPROVE_RESPECT,
        reason=f"Награда за одобренный мем #{item_id}",
        idempotency_key=f"meme-reward:{item_id}",
        grace_entry_type=LedgerType.MEME_REWARD,
    )


async def history(session: AsyncSession, user_id: int, limit: int = 20) -> list[LedgerEntry]:
    rows = await session.scalars(
        select(LedgerEntry)
        .where(LedgerEntry.account_user_id == user_id)
        .order_by(LedgerEntry.created_at.desc(), LedgerEntry.id.desc())
        .limit(limit)
    )
    return list(rows)
