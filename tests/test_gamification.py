from datetime import date, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from lab21_bot.models import CommunityRank, StaffRole, User
from lab21_bot.services.bless import BlessError, bless_member
from lab21_bot.services.presence import (
    clear_cooldowns_for_tests,
    cooldown_remaining,
    set_cooldown,
)
from lab21_bot.services.quests import QuestError, complete_quest, create_quest, join_quest
from lab21_bot.services.ritual import RitualError, perform_ritual
from lab21_bot.services.seasons import SeasonError, active_season, create_season
from zoneinfo import ZoneInfo


async def test_ritual_streak_and_idempotent_day(session: AsyncSession) -> None:
    user = User(
        telegram_id=101,
        full_name="Адепт",
        is_approved=True,
        rank=CommunityRank.ADEPT,
        balance=100,
    )
    session.add(user)
    await session.flush()
    tz = ZoneInfo("Europe/Moscow")
    today = date(2026, 8, 7)

    first = await perform_ritual(session, user, tz=tz, today=today)
    assert first.grace >= 3
    assert first.streak == 1

    with pytest.raises(RitualError):
        await perform_ritual(session, user, tz=tz, today=today)

    second = await perform_ritual(session, user, tz=tz, today=today + timedelta(days=1))
    assert second.streak == 2

    user.ritual_last_at = today + timedelta(days=1)
    skipped = await perform_ritual(session, user, tz=tz, today=today + timedelta(days=3))
    assert skipped.streak == 1


def test_ritual_denied_names_command() -> None:
    from lab21_bot.data import phrase

    text = phrase("ritual", "denied")
    assert "/bow" in text
    assert "участникам сообщества" in text


async def test_ritual_streak_bonus_every_7(session: AsyncSession) -> None:
    user = User(
        telegram_id=102,
        full_name="Послушник",
        is_approved=True,
        balance=50,
        ritual_streak=6,
        ritual_last_at=date(2026, 8, 6),
    )
    session.add(user)
    await session.flush()
    result = await perform_ritual(
        session, user, tz=ZoneInfo("UTC"), today=date(2026, 8, 7)
    )
    assert result.streak == 7
    assert result.streak_bonus is True
    assert result.grace >= 3 + 7
    assert user.respect >= 1


async def test_bless_limits(session: AsyncSession) -> None:
    actor = User(telegram_id=1, full_name="Лорд", staff_role=StaffRole.LORD, is_approved=True)
    target = User(telegram_id=2, full_name="Адепт", is_approved=True, balance=10)
    other = User(telegram_id=3, full_name="Другой", is_approved=True, balance=10)
    session.add_all([actor, target, other])
    await session.flush()

    await bless_member(session, actor, target)
    assert target.respect == 1

    with pytest.raises(BlessError):
        await bless_member(session, actor, other)

    with pytest.raises(BlessError):
        await bless_member(session, actor, actor)


async def test_quest_join_and_complete(session: AsyncSession) -> None:
    staff = User(
        telegram_id=10, full_name="Магистр", staff_role=StaffRole.MAGISTER, is_approved=True
    )
    member = User(
        telegram_id=20,
        full_name="Паяльщик",
        is_approved=True,
        skill_ids=["soldering"],
        balance=0,
    )
    session.add_all([staff, member])
    await session.flush()

    quest = await create_quest(
        session,
        staff,
        title="Собрать стенд",
        description="Нужны руки",
        skill_ids=["soldering"],
        required_participants=1,
        grace_reward=10,
        respect_reward=2,
    )
    await join_quest(session, quest, member)
    with pytest.raises(QuestError):
        await join_quest(session, quest, member)

    await complete_quest(session, staff, quest.id, {member.telegram_id: 100.0})
    await session.refresh(member)
    assert member.balance == 10
    assert member.respect == 2


async def test_quest_join_rejects_missing_skill_and_full(session: AsyncSession) -> None:
    from lab21_bot.data import phrase
    from lab21_bot.services.quests import leave_quest

    staff = User(
        telegram_id=13, full_name="Магистр", staff_role=StaffRole.MAGISTER, is_approved=True
    )
    skilled = User(
        telegram_id=21,
        full_name="Паяльщик",
        is_approved=True,
        skill_ids=["soldering"],
        balance=0,
    )
    unskilled = User(
        telegram_id=22,
        full_name="Новичок",
        is_approved=True,
        skill_ids=[],
        balance=0,
    )
    extra = User(
        telegram_id=23,
        full_name="Второй",
        is_approved=True,
        skill_ids=["soldering"],
        balance=0,
    )
    session.add_all([staff, skilled, unskilled, extra])
    await session.flush()

    quest = await create_quest(
        session,
        staff,
        title="Пайка",
        description="Нужен навык",
        skill_ids=["soldering"],
        required_participants=1,
        grace_reward=5,
        respect_reward=1,
    )
    with pytest.raises(QuestError, match=phrase("quests", "missing_skill_alert")):
        await join_quest(session, quest, unskilled)

    await join_quest(session, quest, skilled)
    with pytest.raises(QuestError, match=phrase("quests", "full")):
        await join_quest(session, quest, extra)

    await leave_quest(session, quest.id, skilled.telegram_id)
    await join_quest(session, quest, extra)


def test_quest_post_copy_and_keyboard() -> None:
    from lab21_bot.keyboards import quest_card_keyboard
    from lab21_bot.models import CommunityQuest
    from lab21_bot.services.quests import format_quest_html

    quest = CommunityQuest(
        number=7,
        title="Стенд",
        description="Собрать",
        skill_ids=["soldering"],
        required_participants=3,
        grace_reward=20,
        respect_reward=4,
    )
    html = format_quest_html(quest, [])
    assert "Максимум участников: 3" in html
    assert "Награда: 20 🙏 / 4 ❇" in html
    assert "Поставь" not in html
    assert "Нужно участников" not in html
    join = quest_card_keyboard(9, joined=False)
    assert join.inline_keyboard[0][0].text == "Участвовать"
    assert join.inline_keyboard[0][0].callback_data == "quest_join:9"
    leave = quest_card_keyboard(9, joined=True)
    assert leave.inline_keyboard[0][0].text == "Отписаться"
    assert leave.inline_keyboard[0][0].callback_data == "quest_leave:9"


def test_gamification_admin_has_upload_helpers() -> None:
    from lab21_bot.admin.routes import gamification

    assert gamification.UploadError is not None
    assert gamification.save_quest_image is not None


def test_telegram_not_modified_detection() -> None:
    from lab21_bot.services.quests import _telegram_not_modified

    assert _telegram_not_modified(Exception("Bad Request: message is not modified"))
    assert not _telegram_not_modified(Exception("message to edit not found"))


async def test_edit_quest_post_html_skips_without_ids() -> None:
    from unittest.mock import AsyncMock

    from lab21_bot.models import CommunityQuest
    from lab21_bot.services.quests import edit_quest_post_html

    bot = AsyncMock()
    quest = CommunityQuest(number=1, title="t", description="d")
    assert await edit_quest_post_html(bot, quest, "<b>x</b>") is False
    bot.edit_message_text.assert_not_called()
    bot.edit_message_caption.assert_not_called()


async def test_sync_quest_resends_when_edit_fails() -> None:
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, MagicMock

    from aiogram.exceptions import TelegramBadRequest

    from lab21_bot.models import CommunityQuest, CommunityQuestStatus
    from lab21_bot.services.quests import sync_quest_telegram_post

    quest = CommunityQuest(
        number=1,
        title="t",
        description="d",
        status=CommunityQuestStatus.OPEN,
        chat_id=-100,
        message_id=42,
        required_participants=1,
        grace_reward=1,
        respect_reward=1,
    )
    bot = AsyncMock()
    bot.edit_message_text.side_effect = TelegramBadRequest(
        method=MagicMock(),
        message="Bad Request: message can't be edited",
    )
    bot.edit_message_caption.side_effect = TelegramBadRequest(
        method=MagicMock(),
        message="Bad Request: there is no caption in the message to edit",
    )
    sent = SimpleNamespace(chat=SimpleNamespace(id=-100), message_id=99, photo=None)
    bot.send_message.return_value = sent

    await sync_quest_telegram_post(bot, quest, [], message_thread_id=5)
    bot.delete_message.assert_awaited()
    bot.send_message.assert_awaited()
    assert quest.message_id == 99


async def test_quest_schedule_range_and_indefinite(session: AsyncSession) -> None:
    from lab21_bot.services.quests import format_quest_schedule, validate_quest_schedule

    staff = User(
        telegram_id=12, full_name="Магистр", staff_role=StaffRole.MAGISTER, is_approved=True
    )
    session.add(staff)
    await session.flush()

    assert validate_quest_schedule(quest_date=None, quest_ends_on=None) == (None, None)
    with pytest.raises(QuestError):
        validate_quest_schedule(quest_date=date(2026, 8, 10), quest_ends_on=None)
    with pytest.raises(QuestError):
        validate_quest_schedule(
            quest_date=date(2026, 8, 12), quest_ends_on=date(2026, 8, 10)
        )

    open_quest = await create_quest(
        session,
        staff,
        title="Бессрочный",
        description="Всегда",
        skill_ids=[],
        required_participants=1,
        grace_reward=1,
        respect_reward=0,
    )
    assert format_quest_schedule(open_quest) == "Бессрочный"

    day = await create_quest(
        session,
        staff,
        title="Один день",
        description="Сегодня",
        skill_ids=[],
        required_participants=1,
        grace_reward=1,
        respect_reward=0,
        quest_date=date(2026, 8, 10),
        quest_ends_on=date(2026, 8, 10),
    )
    assert format_quest_schedule(day) == "Дата: 2026-08-10"

    span = await create_quest(
        session,
        staff,
        title="Неделя",
        description="Диапазон",
        skill_ids=[],
        required_participants=1,
        grace_reward=1,
        respect_reward=0,
        quest_date=date(2026, 8, 10),
        quest_ends_on=date(2026, 8, 17),
    )
    assert format_quest_schedule(span) == "Даты: 2026-08-10 — 2026-08-17"


async def test_quest_media_create_and_clear(session: AsyncSession) -> None:
    from lab21_bot.services.quests import (
        media_photo_entry,
        quest_has_image,
        quest_image_path,
        update_quest,
    )

    staff = User(
        telegram_id=11, full_name="Магистр", staff_role=StaffRole.MAGISTER, is_approved=True
    )
    session.add(staff)
    await session.flush()

    quest = await create_quest(
        session,
        staff,
        title="С фото",
        description="Картинка",
        skill_ids=[],
        required_participants=1,
        grace_reward=1,
        respect_reward=0,
        media=[media_photo_entry(path="quests/1_test.jpg")],
    )
    assert quest_has_image(quest)
    assert quest_image_path(quest) == "quests/1_test.jpg"

    updated = await update_quest(session, staff, quest.id, clear_media=True)
    assert not quest_has_image(updated)
    assert quest_image_path(updated) is None


async def test_season_active_window(session: AsyncSession) -> None:
    lord = User(telegram_id=1, full_name="Лорд", staff_role=StaffRole.LORD, is_approved=True)
    session.add(lord)
    await session.flush()
    await create_season(
        session,
        lord,
        code="halloween",
        title="Dark Halloween",
        description="Буу",
        starts_on=date(2026, 10, 25),
        ends_on=date(2026, 11, 5),
        meme_collection="halloween",
        phrases_key="halloween",
    )
    assert await active_season(session, today=date(2026, 10, 20)) is None
    active = await active_season(session, today=date(2026, 10, 31))
    assert active is not None
    assert active.meme_collection == "halloween"

    with pytest.raises(SeasonError):
        await create_season(
            session,
            lord,
            code="halloween",
            title="dup",
            description="",
            starts_on=date(2026, 1, 1),
            ends_on=date(2026, 1, 2),
        )


def test_season_announce_placeholders_match_format_fields() -> None:
    from lab21_bot.services.seasons import SEASON_ANNOUNCE_PLACEHOLDERS

    tokens = {item["token"] for item in SEASON_ANNOUNCE_PLACEHOLDERS}
    assert tokens == {"{title}", "{description}", "{starts_on}", "{ends_on}", "{code}"}
    assert all(item["hint"].strip() for item in SEASON_ANNOUNCE_PLACEHOLDERS)


def test_format_season_announce_custom_and_fallback() -> None:
    from lab21_bot.models import SeasonEvent
    from lab21_bot.services.seasons import format_season_announce

    season = SeasonEvent(
        code="halloween",
        title="Dark Halloween",
        description="Буу",
        starts_on=date(2026, 10, 25),
        ends_on=date(2026, 11, 5),
        start_message="Старт: {title}\n{description}",
        end_message="",
    )
    assert format_season_announce(season, "start") == "Старт: Dark Halloween\nБуу"
    end = format_season_announce(season, "end")
    assert "Dark Halloween" in end
    assert "завершён" in end


def test_season_year_map_layout() -> None:
    from lab21_bot.models import SeasonEvent
    from lab21_bot.services.seasons import build_season_year_map

    halloween = SeasonEvent(
        id=1,
        code="halloween",
        title="Dark Halloween",
        starts_on=date(2026, 10, 25),
        ends_on=date(2026, 11, 5),
        is_enabled=True,
    )
    nye = SeasonEvent(
        id=2,
        code="nye",
        title="Новый год",
        starts_on=date(2025, 12, 20),
        ends_on=date(2026, 1, 10),
        is_enabled=True,
    )
    off = SeasonEvent(
        id=3,
        code="april",
        title="Первое апреля",
        starts_on=date(2026, 4, 1),
        ends_on=date(2026, 4, 1),
        is_enabled=False,
    )
    other_year = SeasonEvent(
        id=4,
        code="summer25",
        title="Лето",
        starts_on=date(2025, 6, 1),
        ends_on=date(2025, 8, 31),
        is_enabled=True,
    )
    result = build_season_year_map(
        [halloween, nye, off, other_year],
        year=2026,
        today=date(2026, 10, 31),
    )
    assert result["days"] == 365
    assert result["today_pct"] is not None
    assert len(result["months"]) == 12
    assert result["months"][0]["label"] == "янв"
    codes = [row["code"] for row in result["rows"]]
    assert codes == ["nye", "april", "halloween"]
    by_code = {row["code"]: row for row in result["rows"]}
    assert by_code["halloween"]["state"] == "active"
    assert by_code["nye"]["state"] == "past"
    assert by_code["nye"]["continues_left"] is True
    assert by_code["nye"]["left"] == 0
    assert by_code["april"]["state"] == "off"
    assert by_code["halloween"]["left"] > 70
    leap = build_season_year_map([], year=2028, today=date(2028, 6, 1))
    assert leap["days"] == 366
    assert leap["today_pct"] is not None
    empty = build_season_year_map([halloween], year=2025, today=date(2025, 1, 1))
    assert empty["rows"] == []
    assert empty["today_pct"] is not None


def test_season_phrase_key_select_keeps_unknown_current() -> None:
    from lab21_bot.admin.routes.gamification import _phrase_keys_for_select
    from lab21_bot.data import list_season_phrase_keys

    catalog = {str(item["key"]) for item in list_season_phrase_keys()}
    assert "halloween" in catalog
    items = _phrase_keys_for_select("halloween")
    keys = [str(item["key"]) for item in items]
    assert keys.count("halloween") == 1
    unknown = _phrase_keys_for_select("ny")
    assert "ny" in {str(item["key"]) for item in unknown}


def test_presence_cooldown() -> None:
    clear_cooldowns_for_tests()
    set_cooldown("x", 30)
    assert cooldown_remaining("x") > 0
    clear_cooldowns_for_tests()
    assert cooldown_remaining("x") == 0
