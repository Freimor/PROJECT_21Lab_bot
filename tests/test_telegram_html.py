from lab21_bot.services.telegram_html import normalize_telegram_html
from lab21_bot.services.markdown_lite import render_markdown


def test_normalize_strips_stray_gt_and_converts_fences() -> None:
    raw = (
        "Вспомнил мудрость:\n"
        ">\n"
        "<blockquote>семь раз</blockquote>\n\n"
        "```c\n"
        'printf("Hello");\n'
        "```\n"
    )
    out = normalize_telegram_html(raw)
    assert not any(line.strip() == ">" for line in out.splitlines())
    assert "<pre>" in out
    assert "printf" in out
    assert "```" not in out
    assert "<blockquote>семь раз</blockquote>" in out


def test_normalize_markdown_quotes() -> None:
    raw = "Intro\n> quoted line\nEnd"
    out = normalize_telegram_html(raw)
    assert "<blockquote>quoted line</blockquote>" in out
    assert not any(line.startswith(">") for line in out.splitlines())


def test_render_markdown_basic() -> None:
    html = render_markdown("# Title\n\nHello **bold** and `code`.\n\n- one\n- two\n")
    assert "<h1>Title</h1>" in html
    assert "<strong>bold</strong>" in html
    assert "<code>code</code>" in html
    assert "<li>one</li>" in html


def test_render_markdown_table() -> None:
    source = (
        "| Тема | Где |\n"
        "|------|-----|\n"
        "| Навыки | `data/skills.json` |\n"
        "| Роли | админка |\n"
    )
    html = render_markdown(source)
    assert "<table" in html
    assert "<th>Тема</th>" in html
    assert "<th>Где</th>" in html
    assert "<td>Навыки</td>" in html
    assert "<code>data/skills.json</code>" in html
    assert "|------|" not in html
