from types import SimpleNamespace

import pytest

from lab21_bot.models import ContentKind
from lab21_bot.services.destinations import (
    DestinationError,
    destination_for_kind,
    flood_destination,
    matches_destination,
)


def _settings(**kwargs: object) -> SimpleNamespace:
    base = {
        "main_channel_id": -100111,
        "important_channel_id": None,
        "flood_chat_id": None,
        "main_thread_id": 2,
        "important_thread_id": 3,
        "flood_thread_id": 4,
    }
    base.update(kwargs)
    return SimpleNamespace(**base)


def test_forum_destinations_share_chat_id() -> None:
    settings = _settings()
    story = destination_for_kind(settings, ContentKind.STORY)
    important = destination_for_kind(settings, ContentKind.IMPORTANT)
    meme = destination_for_kind(settings, ContentKind.MEME)
    assert story == destination_for_kind(settings, ContentKind.STORY)
    assert story.chat_id == important.chat_id == meme.chat_id == -100111
    assert story.thread_id == 2
    assert important.thread_id == 3
    assert meme.thread_id == 4


def test_flood_disabled_without_chat_or_thread() -> None:
    settings = _settings(flood_thread_id=None, flood_chat_id=None)
    assert flood_destination(settings) is None
    with pytest.raises(DestinationError):
        destination_for_kind(settings, ContentKind.MEME)


def test_matches_destination_by_thread() -> None:
    settings = _settings()
    assert matches_destination(
        settings, chat_id=-100111, thread_id=2, kind=ContentKind.STORY
    )
    assert not matches_destination(
        settings, chat_id=-100111, thread_id=3, kind=ContentKind.STORY
    )
    assert matches_destination(
        settings, chat_id=-100111, thread_id=3, kind=ContentKind.IMPORTANT
    )


def test_job_destination() -> None:
    from lab21_bot.services.destinations import job_destination

    settings = _settings(job_thread_id=5, job_chat_id=None, job_channel_id=None)
    dest = job_destination(settings)
    assert dest is not None
    assert dest.chat_id == -100111
    assert dest.thread_id == 5
    assert job_destination(_settings(job_thread_id=None, job_chat_id=None, job_channel_id=None)) is None

    dedicated = job_destination(
        _settings(job_chat_id=None, job_channel_id=-100222, job_thread_id=None)
    )
    assert dedicated is not None
    assert dedicated.chat_id == -100222
    assert dedicated.thread_id is None


def test_shop_destination() -> None:
    from lab21_bot.services.destinations import shop_destination

    settings = _settings(shop_thread_id=7, shop_chat_id=None)
    dest = shop_destination(settings)
    assert dest is not None
    assert dest.chat_id == -100111
    assert dest.thread_id == 7
    assert shop_destination(_settings(shop_thread_id=None, shop_chat_id=None)) is None

    dedicated = shop_destination(_settings(shop_chat_id=-100333, shop_thread_id=None))
    assert dedicated is not None
    assert dedicated.chat_id == -100333
    assert dedicated.thread_id is None


def test_bugs_destination_disabled_when_unset() -> None:
    from lab21_bot.services.destinations import bugs_destination, matches_bugs_destination

    settings = _settings(bugs_chat_id=None, bugs_thread_id=None)
    assert bugs_destination(settings) is None
    assert not matches_bugs_destination(settings, chat_id=-100111, thread_id=65)


def test_bugs_destination_uses_main_chat() -> None:
    from lab21_bot.services.destinations import bugs_destination, matches_bugs_destination

    settings = _settings(bugs_chat_id=None, bugs_thread_id=65)
    dest = bugs_destination(settings)
    assert dest is not None
    assert dest.chat_id == -100111
    assert dest.thread_id == 65
    assert matches_bugs_destination(settings, chat_id=-100111, thread_id=65)
    assert not matches_bugs_destination(settings, chat_id=-100111, thread_id=6)
