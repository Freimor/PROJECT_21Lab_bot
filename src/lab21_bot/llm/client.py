from __future__ import annotations

import asyncio
import re
from typing import Any

import httpx

from lab21_bot.config import Settings
from lab21_bot.llm.prompts import (
    interview_post_prompt,
    job_post_prompt,
    staff_post_prompt,
    system_prompt,
)
from lab21_bot.services.llm_config import (
    DEFAULT_COMMAND_SUFFIX,
    DEFAULT_TEMPERATURE,
    LlmRuntime,
    default_prompts,
)
from lab21_bot.services.telegram_html import normalize_telegram_html

_FENCE_RE = re.compile(
    r"^\s*```(?:html|HTML)?\s*\n?(.*?)\n?```\s*$",
    re.DOTALL,
)


class LLMError(RuntimeError):
    pass


def strip_llm_fences(text: str) -> str:
    """Remove a wrapping markdown code fence if the model added one."""
    cleaned = text.strip()
    match = _FENCE_RE.match(cleaned)
    if match:
        return match.group(1).strip()
    if cleaned.startswith("```") and cleaned.endswith("```"):
        inner = cleaned[3:-3].strip()
        if inner.lower().startswith("html"):
            inner = inner[4:].lstrip("\r\n")
        return inner.strip()
    return cleaned


class LLMClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._client = httpx.AsyncClient(timeout=settings.llm_timeout_seconds)

    async def close(self) -> None:
        await self._client.aclose()

    def _runtime_or_defaults(self, runtime: LlmRuntime | None) -> LlmRuntime:
        if runtime is not None:
            return runtime
        return LlmRuntime(
            model=self.settings.llm_model,
            temperature=DEFAULT_TEMPERATURE,
            timeout_seconds=self.settings.llm_timeout_seconds,
            command_suffix=DEFAULT_COMMAND_SUFFIX,
            prompts=default_prompts(),
        )

    async def ping(self) -> bool:
        if self.settings.llm_provider == "openvino":
            from lab21_bot.llm.openvino_backend import ping_sync

            try:
                return await asyncio.to_thread(
                    ping_sync,
                    self.settings.llm_model,
                    self.settings.llm_device,
                )
            except Exception:
                return False
        if self.settings.llm_provider == "openai":
            try:
                response = await self._client.get(
                    f"{self.settings.llm_base_url.rstrip('/')}/v1/models",
                    timeout=5.0,
                )
                return response.status_code < 500
            except httpx.HTTPError:
                return False
        try:
            response = await self._client.get(
                f"{self.settings.llm_base_url.rstrip('/')}/api/tags",
                timeout=5.0,
            )
            response.raise_for_status()
            return True
        except httpx.HTTPError:
            return False

    async def list_models(self) -> list[str]:
        if self.settings.llm_provider == "openvino":
            return [self.settings.llm_model]
        if self.settings.llm_provider == "openai":
            try:
                headers: dict[str, str] = {}
                if self.settings.llm_api_key:
                    headers["Authorization"] = (
                        f"Bearer {self.settings.llm_api_key.get_secret_value()}"
                    )
                response = await self._client.get(
                    f"{self.settings.llm_base_url.rstrip('/')}/v1/models",
                    headers=headers,
                    timeout=10.0,
                )
                response.raise_for_status()
                payload = response.json()
            except (httpx.HTTPError, ValueError, TypeError) as error:
                raise LLMError("Не удалось получить список моделей LLM") from error
            models: list[str] = []
            for item in payload.get("data") or []:
                if isinstance(item, dict) and item.get("id"):
                    models.append(str(item["id"]))
            return sorted(set(models)) or [self.settings.llm_model]
        try:
            response = await self._client.get(
                f"{self.settings.llm_base_url.rstrip('/')}/api/tags",
                timeout=10.0,
            )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError, TypeError) as error:
            raise LLMError("Не удалось получить список моделей Ollama") from error
        models = []
        for item in payload.get("models") or []:
            if not isinstance(item, dict):
                continue
            name = item.get("name") or item.get("model")
            if name:
                models.append(str(name))
        return sorted(set(models))

    async def generate_staff_post(
        self,
        note: str,
        *,
        interview: bool = False,
        job: bool = False,
        runtime: LlmRuntime | None = None,
    ) -> str:
        if not note.strip():
            raise LLMError("Заметка пуста")
        cfg = self._runtime_or_defaults(runtime)
        if job:
            prompt = job_post_prompt(
                note, prompts=cfg.prompts, command_suffix=cfg.command_suffix
            )
        elif interview:
            prompt = interview_post_prompt(
                note, prompts=cfg.prompts, command_suffix=cfg.command_suffix
            )
        else:
            prompt = staff_post_prompt(
                note, prompts=cfg.prompts, command_suffix=cfg.command_suffix
            )
        if self.settings.llm_provider == "ollama":
            return await self._ollama(prompt, cfg)
        if self.settings.llm_provider == "openvino":
            return await self._openvino(prompt, cfg)
        return await self._openai(prompt, cfg)

    async def _openvino(self, prompt: str, runtime: LlmRuntime) -> str:
        from lab21_bot.llm.openvino_backend import OpenVinoGenerateRequest, generate_sync

        req = OpenVinoGenerateRequest(
            system=system_prompt(runtime.prompts),
            user=prompt,
            model_path=runtime.model,
            device=self.settings.llm_device,
            temperature=runtime.temperature,
            max_new_tokens=self.settings.llm_max_new_tokens,
        )
        try:
            text = await asyncio.wait_for(
                asyncio.to_thread(generate_sync, req),
                timeout=runtime.timeout_seconds,
            )
        except TimeoutError as error:
            raise LLMError(
                f"OpenVINO ({self.settings.llm_device}) не успел ответить за "
                f"{runtime.timeout_seconds:.0f} с — увеличьте таймаут в настройках LLM"
            ) from error
        except Exception as error:
            raise LLMError(f"OpenVINO ошибка: {error}") from error
        text = strip_llm_fences(text)
        text = normalize_telegram_html(text)
        if not text:
            raise LLMError("Локальная LLM вернула пустой ответ")
        return text

    async def _ollama(self, prompt: str, runtime: LlmRuntime) -> str:
        try:
            response = await self._client.post(
                f"{self.settings.llm_base_url.rstrip('/')}/api/chat",
                json={
                    "model": runtime.model,
                    "stream": False,
                    "think": False,
                    "messages": [
                        {"role": "system", "content": system_prompt(runtime.prompts)},
                        {"role": "user", "content": prompt},
                    ],
                    "options": {"temperature": runtime.temperature},
                },
                timeout=runtime.timeout_seconds,
            )
        except httpx.TimeoutException as error:
            raise LLMError(
                f"Ollama не успела ответить за {runtime.timeout_seconds:.0f} с "
                "(на CPU длинные посты могут занимать много минут — увеличьте таймаут "
                "в настройках LLM или возьмите более быструю модель)"
            ) from error
        except httpx.HTTPError as error:
            raise LLMError("Ollama недоступна") from error
        if response.status_code >= 400:
            detail = ""
            try:
                payload = response.json()
                detail = str(payload.get("error") or payload.get("message") or "")
            except (ValueError, TypeError):
                detail = response.text[:200]
            raise LLMError(
                f"Ollama вернула ошибку {response.status_code}"
                + (f": {detail}" if detail else "")
            )
        return self._extract(response, ("message", "content"))

    async def _openai(self, prompt: str, runtime: LlmRuntime) -> str:
        headers: dict[str, str] = {}
        if self.settings.llm_api_key:
            headers["Authorization"] = f"Bearer {self.settings.llm_api_key.get_secret_value()}"
        try:
            response = await self._client.post(
                f"{self.settings.llm_base_url.rstrip('/')}/v1/chat/completions",
                headers=headers,
                json={
                    "model": runtime.model,
                    "messages": [
                        {"role": "system", "content": system_prompt(runtime.prompts)},
                        {"role": "user", "content": prompt},
                    ],
                    "temperature": runtime.temperature,
                    "max_tokens": self.settings.llm_max_new_tokens,
                },
                timeout=runtime.timeout_seconds,
            )
        except httpx.TimeoutException as error:
            raise LLMError(
                f"LLM не успела ответить за {runtime.timeout_seconds:.0f} с"
            ) from error
        except httpx.HTTPError as error:
            raise LLMError("LLM недоступна") from error
        return self._extract(response, ("choices", 0, "message", "content"))

    @staticmethod
    def _extract(response: httpx.Response, path: tuple[str | int, ...]) -> str:
        try:
            response.raise_for_status()
            value: Any = response.json()
            for key in path:
                value = value[key]
            text = strip_llm_fences(str(value))
            text = normalize_telegram_html(text)
        except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as error:
            raise LLMError("Локальная LLM не ответила корректно") from error
        if not text:
            raise LLMError("Локальная LLM вернула пустой ответ")
        return text
