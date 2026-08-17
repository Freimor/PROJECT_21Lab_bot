from types import SimpleNamespace

from lab21_bot.middlewares import should_delete_command_message
from lab21_bot.models import FeedbackKind
from lab21_bot.services.feedback import clean_feedback_text, detect_feedback_kind


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


def test_keeps_bug_and_upgrade_command_messages() -> None:
    assert should_delete_command_message(_command_message("/bug камера")) is False
    assert should_delete_command_message(_command_message("/upgrade идея")) is False
    assert should_delete_command_message(_command_message("/bug@lab_bot текст")) is False
    assert should_delete_command_message(_command_message("/card")) is True
    assert should_delete_command_message(_command_message("/start")) is True
    plain = SimpleNamespace(entities=None, text="просто текст")
    assert should_delete_command_message(plain) is False
