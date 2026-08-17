from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from lab21_bot.models import CommunityRank, LedgerEntry, StaffRole, User
from lab21_bot.services.economy import EconomyError, change_balance, change_respect, transfer


async def test_grant_withdraw_and_idempotency(session: AsyncSession) -> None:
    actor = User(telegram_id=1, full_name="Лорд", staff_role=StaffRole.LORD)
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
        balance=250,
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
    assert sender.balance == 220
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


async def test_transfer_keeps_base_grace(session: AsyncSession) -> None:
    sender = User(
        telegram_id=11,
        full_name="Первый",
        rank=CommunityRank.ADEPT,
        balance=160,
        is_approved=True,
    )
    recipient = User(
        telegram_id=21,
        full_name="Второй",
        rank=CommunityRank.ADEPT,
        is_approved=True,
    )
    session.add_all([sender, recipient])
    await session.flush()

    with pytest.raises(EconomyError, match="базовой 🙏"):
        await transfer(
            session,
            sender.telegram_id,
            recipient.telegram_id,
            20,
            "Слишком много",
            0,
            idempotency_key="transfer-base-1",
        )

    await transfer(
        session,
        sender.telegram_id,
        recipient.telegram_id,
        10,
        "Излишек",
        0,
        idempotency_key="transfer-base-2",
    )
    assert sender.balance == 150
    assert recipient.balance == 10


async def test_transfer_is_idempotent(session: AsyncSession) -> None:
    sender = User(
        telegram_id=100,
        full_name="Первый",
        rank=CommunityRank.ADEPT,
        balance=200,
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
    assert sender.balance == 190
    assert recipient.balance == 10


async def test_respect_grant_withdraw_no_transfer(session: AsyncSession) -> None:
    actor = User(telegram_id=1, full_name="Лорд", staff_role=StaffRole.LORD)
    target = User(telegram_id=2, full_name="Адепт", is_approved=True)
    session.add_all([actor, target])
    await session.flush()

    await change_respect(
        session,
        actor,
        target.telegram_id,
        10,
        "За вклад",
        grant=True,
        idempotency_key="respect-1",
    )
    assert target.respect == 10
    assert target.balance == 0

    await change_respect(
        session,
        actor,
        target.telegram_id,
        3,
        "Коррекция",
        grant=False,
        idempotency_key="respect-2",
    )
    assert target.respect == 7

    staff = User(telegram_id=3, full_name="Смотрящий", staff_role=StaffRole.WATCHER)
    session.add(staff)
    await session.flush()
    with pytest.raises(EconomyError, match="сотрудников"):
        await change_respect(
            session,
            actor,
            staff.telegram_id,
            1,
            "Нельзя",
            grant=True,
        )


async def test_content_rewards_idempotent(session: AsyncSession) -> None:
    from lab21_bot.models import LedgerType
    from lab21_bot.services.economy import reward_meme_approve, reward_post_publish

    author = User(
        telegram_id=50,
        full_name="Автор",
        is_approved=True,
        balance=0,
        respect=0,
    )
    session.add(author)
    await session.flush()

    await reward_post_publish(session, item_id=7, author_id=50)
    await reward_post_publish(session, item_id=7, author_id=50)
    assert author.balance == 20
    assert author.respect == 5

    await reward_meme_approve(session, item_id=9, author_id=50)
    await reward_meme_approve(session, item_id=9, author_id=50)
    assert author.balance == 25
    assert author.respect == 6

    types = set(await session.scalars(select(LedgerEntry.entry_type)))
    assert LedgerType.POST_REWARD in types
    assert LedgerType.MEME_REWARD in types
    assert LedgerType.RESPECT_GRANT in types
