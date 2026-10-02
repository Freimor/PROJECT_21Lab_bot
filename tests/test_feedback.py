from types import SimpleNamespace

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from lab21_bot.middlewares import should_delete_command_message
from lab21_bot.models import FeedbackKind, FeedbackReport, FeedbackStatus, StaffRole, User
from lab21_bot.services.feedback import (
    FeedbackError,
    clean_feedback_text,
    complete_feedback,
    decide_feedback,
    detect_feedback_kind,
)


def _command_message(text: str) -> SimpleNamespace:
    command = text.split()[0]
    return SimpleNamespace(
        entities=[SimpleNamespace(type="bot_command", offset=0, length=len(command))],
        text=text,
    )


def test_detect_feedback_kind() -> None:
    assert detect_feedback_kind("/bug камера не фокусирует") is FeedbackKind.BUG
    assert detect_feedback_kind("/bug@lab_bot broken") is FeedbackKind.BUG
    assert detect_feedback_kind("/upgrade кнопка заказа") is FeedbackKind.UPGRADE
    assert detect_feedback_kind("просто текст") is None
    assert detect_feedback_kind("/bug and /upgrade") is None


def test_clean_feedback_text_strips_command() -> None:
    assert clean_feedback_text("/bug камера не фокусирует") == "камера не фокусирует"
    assert clean_feedback_text("/upgrade@bot идея") == "идея"
    assert clean_feedback_text("/bug") == ""
    assert clean_feedback_text("/bug@lab_bot") == ""


def test_keeps_bug_and_upgrade_command_messages() -> None:
    assert should_delete_command_message(_command_message("/bug камера")) is False
    assert should_delete_command_message(_command_message("/upgrade идея")) is False
    assert should_delete_command_message(_command_message("/bug@lab_bot текст")) is False
    assert should_delete_command_message(_command_message("/card")) is True
    assert should_delete_command_message(_command_message("/start")) is True
    plain = SimpleNamespace(entities=None, text="просто текст")
    assert should_delete_command_message(plain) is False


def _report(*, status: FeedbackStatus = FeedbackStatus.PENDING) -> FeedbackReport:
    return FeedbackReport(
        kind=FeedbackKind.BUG,
        status=status,
        author_name="Инженер",
        chat_id=-100,
        message_id=10,
        text="камера не фокусирует",
        media=[],
    )


async def test_complete_feedback_marks_accepted_done(session: AsyncSession) -> None:
    watcher = User(telegram_id=2, full_name="Смотрящий", staff_role=StaffRole.WATCHER)
    report = _report()
    session.add_all([watcher, report])
    await session.flush()
    row = await decide_feedback(session, watcher, report.id, accept=True, note="берём")
    assert row.status is FeedbackStatus.ACCEPTED

    done = await complete_feedback(session, watcher, row.id)
    assert done.status is FeedbackStatus.DONE
    assert done.decision_note == "берём"


async def test_complete_feedback_requires_accepted(session: AsyncSession) -> None:
    watcher = User(telegram_id=2, full_name="Смотрящий", staff_role=StaffRole.WATCHER)
    report = _report()
    session.add_all([watcher, report])
    await session.flush()
    with pytest.raises(FeedbackError, match="принятой"):
        await complete_feedback(session, watcher, report.id)
