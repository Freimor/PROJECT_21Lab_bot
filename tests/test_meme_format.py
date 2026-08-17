from lab21_bot.models import CommunityRank, ContentTemplate, TemplateKind, User
from lab21_bot.services.attribution import (
    author_title_for_user,
    format_author_footer_for_user,
    format_author_footer_html,
)
from lab21_bot.services.memes import format_meme_post_html, strip_meme_signature
from lab21_bot.data import respect_prefix


def test_strip_meme_signature() -> None:
    raw = "Текст мема\n\n— Pavel | обычный адепт | @rikky_tikki_tavi"
    assert strip_meme_signature(raw) == "Текст мема"
    assert strip_meme_signature("Только текст") == "Только текст"


def test_respect_prefix_tiers() -> None:
    assert respect_prefix(0) == "обычный"
    assert respect_prefix(10) == "обычный"
    assert respect_prefix(11) == "узнаваемый"
    assert respect_prefix(300) == "ветеран"
    assert respect_prefix(301) == "легенда"
    assert respect_prefix(3000) == "омниссия"


def test_format_author_footer_html() -> None:
    html = format_author_footer_html(
        author_name="Ricky Shade",
        author_username="RickyShade",
        title="обычный адепт",
    )
    assert html == "— <i>Ricky Shade</i> | обычный адепт"
    assert "@" not in html


def test_format_meme_post_html_with_username() -> None:
    html = format_meme_post_html(
        "Сколько опыта не имей<",
        author_name="Pavel",
        author_username="rikky_tikki_tavi",
        author_title="обычный адепт",
    )
    assert html == (
        "<blockquote>Сколько опыта не имей&lt;</blockquote>\n"
        "— <i>Pavel</i> | обычный адепт"
    )
    assert "@" not in html


def test_format_meme_post_html_photo_only() -> None:
    html = format_meme_post_html(
        "(фото)",
        author_name="Reiko Shade",
        author_username="ReikoShade",
        author_title="узнаваемый адепт",
    )
    assert html == "— <i>Reiko Shade</i> | узнаваемый адепт"
    assert "blockquote" not in html
    assert "(фото)" not in html
    assert "@" not in html


def test_format_meme_post_html_gif_only() -> None:
    html = format_meme_post_html(
        "(GIF)",
        author_name="ms_Charlotte",
        author_title="обычный послушник",
    )
    assert html == "— <i>ms_Charlotte</i> | обычный послушник"
    assert "blockquote" not in html
    assert "(GIF)" not in html
    assert "(gif)" not in html.lower()


def test_format_meme_post_html_empty_body() -> None:
    html = format_meme_post_html(
        "",
        author_name="Reiko Shade",
        author_username="ReikoShade",
        author_title="обычный послушник",
    )
    assert html == "— <i>Reiko Shade</i> | обычный послушник"


def test_format_strips_old_signature() -> None:
    html = format_meme_post_html(
        "Мем\n\n— Old (@user)",
        author_name="Pavel",
        author_username="rikky_tikki_tavi",
        author_title="обычный адепт",
    )
    assert "Old" not in html
    assert "<blockquote>Мем</blockquote>" in html


def test_meme_post_html_from_template_uses_author() -> None:
    from lab21_bot.services.memes import meme_post_html_from_template

    author = User(
        telegram_id=1,
        full_name="Pavel",
        username="rikky_tikki_tavi",
        is_approved=True,
        is_active=True,
        respect=0,
        rank=CommunityRank.ADEPT,
    )
    template = ContentTemplate(
        id=1,
        kind=TemplateKind.MEME,
        title="Мем",
        body="Текст",
        author=author,
    )
    html = meme_post_html_from_template(template)
    assert html.endswith("— <i>Pavel</i> | обычный адепт")
    assert "@" not in html
    assert author_title_for_user(author) == "обычный адепт"
    assert "обычный адепт" in format_author_footer_for_user(author)
