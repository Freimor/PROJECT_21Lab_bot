from __future__ import annotations

from lab21_bot.data import interview_data, interview_questions, llm_prompts_data
from lab21_bot.services.llm_config import build_user_prompt, default_prompts

INTERVIEW_QUESTIONS = interview_questions()


def system_prompt(prompts: dict[str, str] | None = None) -> str:
    if prompts and prompts.get("system"):
        return prompts["system"].strip()
    return str(llm_prompts_data()["system"]).strip()


def staff_post_prompt(
    note: str,
    *,
    prompts: dict[str, str] | None = None,
    command_suffix: str = "",
) -> str:
    template = (prompts or default_prompts())["staff_post"]
    return build_user_prompt(template, note, command_suffix=command_suffix)


def interview_post_prompt(
    source: str,
    *,
    prompts: dict[str, str] | None = None,
    command_suffix: str = "",
) -> str:
    template = (prompts or default_prompts())["interview_post"]
    return build_user_prompt(template, source, command_suffix=command_suffix)


def job_post_prompt(
    source: str,
    *,
    prompts: dict[str, str] | None = None,
    command_suffix: str = "",
) -> str:
    template = (prompts or default_prompts())["job_post"]
    return build_user_prompt(template, source, command_suffix=command_suffix)


def interview_intro(*, question: str | None = None) -> str:
    first = question if question is not None else INTERVIEW_QUESTIONS[0]
    return str(interview_data()["intro"]).format(question=first)


def interview_disabled_fallback() -> str:
    return str(interview_data()["disabled_fallback"])


# Backward-compatible alias for imports that still expect a constant.
SYSTEM_PROMPT = system_prompt()
