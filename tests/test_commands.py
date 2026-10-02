from lab21_bot.models import StaffRole, User
from lab21_bot.services.commands import GROUP_COMMANDS, MENU_COMMANDS, commands_for_user


def test_slash_menu_is_only_bow() -> None:
    user = User(telegram_id=1, full_name="Member")
    lord = User(telegram_id=2, full_name="Lord", staff_role=StaffRole.LORD)
    assert [command for command, _description in MENU_COMMANDS] == ["bow"]
    assert [item.command for item in commands_for_user(user)] == ["bow"]
    assert [item.command for item in commands_for_user(lord)] == ["bow"]
    assert [command for command, _description in GROUP_COMMANDS] == ["bow", "bug", "upgrade"]
