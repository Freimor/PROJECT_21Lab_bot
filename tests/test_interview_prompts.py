from lab21_bot.llm.client import strip_llm_fences


def test_strip_llm_fences_html_block() -> None:
    raw = "```html\n<b>Заголовок</b>\n\nТекст\n```"
    assert strip_llm_fences(raw) == "<b>Заголовок</b>\n\nТекст"


def test_strip_llm_fences_plain() -> None:
    raw = "<b>Уже готово</b>"
    assert strip_llm_fences(raw) == raw


def test_interview_questions_count() -> None:
    from lab21_bot.data import interview_questions

    questions = interview_questions()
    assert len(questions) == 4
    assert "как есть" in questions[3].lower() or "оставить" in questions[3].lower()
