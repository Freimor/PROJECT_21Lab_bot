from lab21_bot.llm.prompts import staff_post_prompt
from lab21_bot.services.llm_config import (
    LLM_PROMPT_PLACEHOLDERS,
    build_user_prompt,
    default_prompts,
)
from lab21_bot.services.templates import TEASER_PLACEHOLDERS, render_template


def test_build_user_prompt_appends_suffix() -> None:
    result = build_user_prompt("Текст:\n{source}", "факт", command_suffix="/no_think")
    assert result.endswith("/no_think")
    assert "факт" in result


def test_build_user_prompt_skips_duplicate_suffix() -> None:
    template = "Сделай пост. /no_think\n\n{source}"
    result = build_user_prompt(template, "x", command_suffix="/no_think")
    assert result.count("/no_think") == 1


def test_llm_prompt_placeholders() -> None:
    assert {item["token"] for item in LLM_PROMPT_PLACEHOLDERS} == {"{source}"}
    assert all(item["hint"].strip() for item in LLM_PROMPT_PLACEHOLDERS)


def test_teaser_placeholders_match_render() -> None:
    tokens = {item["token"] for item in TEASER_PLACEHOLDERS}
    assert tokens == {"{name}", "{username}", "{link}"}
    text = render_template("Привет, {name} (@{username}) {link}", name="Анна", username="anna", link="https://t.me/c/1/2")
    assert text == "Привет, Анна (@anna) https://t.me/c/1/2"


def test_default_prompts_have_source() -> None:
    prompts = default_prompts()
    assert "{source}" in prompts["staff_post"]
    assert "{source}" in prompts["interview_post"]
    assert "{source}" in prompts["job_post"]
    assert prompts["system"]


def test_staff_post_prompt_with_suffix() -> None:
    text = staff_post_prompt("заметка", command_suffix="/no_think")
    assert "заметка" in text
    assert "/no_think" in text
