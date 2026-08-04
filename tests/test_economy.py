from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from lab21_bot.models import CommunityRank, LedgerEntry, StaffRole, User
from lab21_bot.services.economy import EconomyError, change_balance, transfer


async def test_grant_withdraw_and_idempotency(session: AsyncSession) -> None:
    actor = User(telegram_id=1, full_name="Магистр", staff_role=StaffRole.MAGISTER)
    target = User(telegram_id=2, full_name="Адепт")
    session.add_all([actor, target])
    await session.flush()

    first = await change_balance(
        session,
        actor,
        target.telegram_id,
        25,
        "Помощь со сборкой",
        grant=True,
        idempotency_key="grant-1",
    )
    repeated = await change_balance(
        session,
        actor,
        target.telegram_id,
        25,
        "Повторный callback",
        grant=True,
        idempotency_key="grant-1",
    )
    await change_balance(
        session,
        actor,
        target.telegram_id,
        5,
        "Дополнительная печать",
        grant=False,
        idempotency_key="withdraw-1",
    )

    assert first.id == repeated.id
    assert target.balance == 20
    assert await session.scalar(select(func.count(LedgerEntry.id))) == 2


async def test_transfer_requires_adepts_and_enforces_daily_limit(
    session: AsyncSession,
) -> None:
    sender = User(
        telegram_id=10,
        full_name="Первый",
        rank=CommunityRank.ADEPT,
        balance=100,
    )
    recipient = User(
        telegram_id=20,
        full_name="Второй",
        rank=CommunityRank.NOVICE,
    )
    session.add_all([sender, recipient])
    await session.flush()

    with pytest.raises(EconomyError, match="Адепт"):
        await transfer(
            session,
            sender.telegram_id,
            recipient.telegram_id,
            10,
            "Спасибо",
            50,
            idempotency_key="transfer-1",
        )

    recipient.rank = CommunityRank.ADEPT
    outgoing, incoming = await transfer(
        session,
        sender.telegram_id,
        recipient.telegram_id,
        30,
        "Спасибо за пайку",
        50,
        idempotency_key="transfer-2",
        now=datetime.now(UTC),
    )
    assert outgoing.delta == -30
    assert incoming.delta == 30
    assert sender.balance == 70
    assert recipient.balance == 30

    with pytest.raises(EconomyError, match="лимит"):
        await transfer(
            session,
            sender.telegram_id,
            recipient.telegram_id,
            21,
            "Ещё помощь",
            50,
            idempotency_key="transfer-3",
            now=datetime.now(UTC),
        )


async def test_transfer_is_idempotent(session: AsyncSession) -> None:
    sender = User(
        telegram_id=100,
        full_name="Первый",
        rank=CommunityRank.ADEPT,
        balance=40,
    )
    recipient = User(
        telegram_id=200,
        full_name="Второй",
        rank=CommunityRank.ADEPT,
    )
    session.add_all([sender, recipient])
    await session.flush()

    first = await transfer(session, 100, 200, 10, "За фикс", 0, idempotency_key="same")
    second = await transfer(session, 100, 200, 10, "За фикс", 0, idempotency_key="same")

    assert first[0].id == second[0].id
    assert sender.balance == 30
    assert recipient.balance == 10
