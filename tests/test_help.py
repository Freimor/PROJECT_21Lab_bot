from lab21_bot.models import CommunityRank, StaffRole, User
from lab21_bot.services.help import build_help_text


def _member() -> User:
    return User(
        telegram_id=10,
        full_name="Member",
        rank=CommunityRank.NOVICE,
        is_approved=True,
        is_active=True,
    )


def _staff(role: StaffRole) -> User:
    return User(
        telegram_id=11,
        full_name="Staff",
        staff_role=role,
        is_approved=True,
        is_active=True,
    )


def test_help_member_has_status_and_order() -> None:
    text = build_help_text(_member())
    assert "Профиль" in text
    assert "Заказать услугу" in text
    assert "Сделать заказ" not in text
    assert "Магазин" in text
    assert "Предложить материал" in text
    assert "Служебное меню" not in text
    assert "Важное" not in text


def test_help_watcher_has_moderation_not_reboot() -> None:
    text = build_help_text(_staff(StaffRole.WATCHER))
    assert "Служебное меню" in text
    assert "Очередь публикаций" in text
    assert "Заказы" in text
    assert "Перезагрузка" not in text
    assert "Профиль" not in text


def test_help_lord_has_important_and_reboot() -> None:
    text = build_help_text(_staff(StaffRole.LORD))
    assert "Важное" in text
    assert "Перезагрузка" in text
    assert "Настройки" in text
