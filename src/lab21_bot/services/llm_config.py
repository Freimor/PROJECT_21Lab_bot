from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from lab21_bot.config import Settings
from lab21_bot.data import llm_prompts_data
from lab21_bot.models import AdminAction, BotSetting, User
from lab21_bot.services.access import Permission, require_permission

DEFAULT_TEMPERATURE = 0.75
DEFAULT_COMMAND_SUFFIX = "/no_think"

PROMPT_KEYS = ("system", "staff_post", "interview_post", "job_post")

LLM_PROMPT_PLACEHOLDERS: tuple[dict[str, str], ...] = (
    {
        "token": "{source}",
        "hint": "Исходный текст заметки, интервью или отчёта по заказу. Обязателен во всех шаблонах, кроме System.",
    },
)

# Soft-switch directives appended to the user prompt (Qwen3 / thinking models).
LLM_COMMAND_LEGEND: tuple[dict[str, str], ...] = (
    {
        "code": "/no_think",
        "desc": "Выключить thinking: модель сразу пишет пост, без скрытой цепочки рассуждений. Быстрее и стабильнее для редактуры. Значение по умолчанию.",
    },
    {
        "code": "/think",
        "desc": "Включить thinking: модель сначала «думает», потом отвечает. Полезно для сложных исходников, но дольше и иногда шумнее.",
    },
    {
        "code": "(пусто)",
        "desc": "Не добавлять суффикс. Поведение зависит от модели и шаблона Ollama (у thinking-моделей часто думают по умолчанию).",
    },
)


class LlmConfigError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class LlmRuntime:
    model: str
    temperature: float
    timeout_seconds: float
    command_suffix: str
    prompts: dict[str, str]


def default_prompts() -> dict[str, str]:
    data = llm_prompts_data()
    return {key: str(data[key]).strip() for key in PROMPT_KEYS}


async def _get_setting_value(session: AsyncSession, key: str) -> Any | None:
    setting = await session.get(BotSetting, key)
    if setting is None:
        return None
    return setting.value.get("value")


async def _set_setting_value(
    session: AsyncSession,
    actor: User,
    key: str,
    value: Any,
) -> BotSetting:
    setting = await session.get(BotSetting, key)
    if setting is None:
        setting = BotSetting(key=key, value={"value": value}, updated_by=actor.telegram_id)
        session.add(setting)
    else:
        setting.value = {"value": value}
        setting.updated_by = actor.telegram_id
    session.add(
        AdminAction(
            actor_id=actor.telegram_id,
            action="set_setting",
            details={"key": key, "value": value},
        )
    )
    await session.flush()
    return setting


def _normalize_prompts(raw: Any) -> dict[str, str]:
    defaults = default_prompts()
    if not isinstance(raw, dict):
        return defaults
    result: dict[str, str] = {}
    for key in PROMPT_KEYS:
        value = raw.get(key)
        text = str(value).strip() if value is not None else ""
        result[key] = text or defaults[key]
    return result


def build_user_prompt(template: str, source: str, *, command_suffix: str) -> str:
    body = template.format(source=source.strip())
    suffix = command_suffix.strip()
    if not suffix:
        return body
    if suffix in body:
        return body
    return f"{body.rstrip()}\n\n{suffix}"


async def get_llm_runtime(session: AsyncSession, settings: Settings) -> LlmRuntime:
    model_raw = await _get_setting_value(session, "llm_model")
    model = str(model_raw).strip() if model_raw is not None else ""
    if not model:
        model = settings.llm_model

    temp_raw = await _get_setting_value(session, "llm_temperature")
    try:
        temperature = float(temp_raw) if temp_raw is not None else DEFAULT_TEMPERATURE
    except (TypeError, ValueError):
        temperature = DEFAULT_TEMPERATURE
    temperature = max(0.0, min(2.0, temperature))

    timeout_raw = await _get_setting_value(session, "llm_timeout_seconds")
    try:
        timeout = float(timeout_raw) if timeout_raw is not None else settings.llm_timeout_seconds
    except (TypeError, ValueError):
        timeout = settings.llm_timeout_seconds
    timeout = max(5.0, min(1800.0, timeout))

    suffix_raw = await _get_setting_value(session, "llm_command_suffix")
    if suffix_raw is None:
        command_suffix = DEFAULT_COMMAND_SUFFIX
    else:
        command_suffix = str(suffix_raw).strip()

    prompts = _normalize_prompts(await _get_setting_value(session, "llm_prompts"))
    return LlmRuntime(
        model=model,
        temperature=temperature,
        timeout_seconds=timeout,
        command_suffix=command_suffix,
        prompts=prompts,
    )


async def save_llm_settings(
    session: AsyncSession,
    actor: User,
    settings: Settings,
    *,
    model: str,
    temperature: float,
    timeout_seconds: float,
    command_suffix: str,
) -> LlmRuntime:
    require_permission(actor, Permission.MANAGE_SETTINGS)
    model_clean = model.strip()
    if not model_clean:
        raise LlmConfigError("Укажите модель")
    if not 0.0 <= temperature <= 2.0:
        raise LlmConfigError("Температура должна быть в диапазоне 0–2")
    if not 5.0 <= timeout_seconds <= 1800.0:
        raise LlmConfigError("Таймаут должен быть в диапазоне 5–1800 секунд")
    await _set_setting_value(session, actor, "llm_model", model_clean)
    await _set_setting_value(session, actor, "llm_temperature", float(temperature))
    await _set_setting_value(session, actor, "llm_timeout_seconds", float(timeout_seconds))
    await _set_setting_value(session, actor, "llm_command_suffix", command_suffix.strip())
    return await get_llm_runtime(session, settings)


async def save_llm_prompts(
    session: AsyncSession,
    actor: User,
    prompts: dict[str, str],
) -> dict[str, str]:
    require_permission(actor, Permission.MANAGE_SETTINGS)
    cleaned = _normalize_prompts(prompts)
    for key in PROMPT_KEYS:
        if not cleaned[key].strip():
            raise LlmConfigError(f"Шаблон «{key}» не может быть пустым")
        if key != "system" and "{source}" not in cleaned[key]:
            raise LlmConfigError(f"В шаблоне «{key}» нужен плейсхолдер {{source}}")
    await _set_setting_value(session, actor, "llm_prompts", cleaned)
    return cleaned
