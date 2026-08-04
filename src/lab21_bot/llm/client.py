from __future__ import annotations

from typing import Any

import httpx

from lab21_bot.config import Settings
from lab21_bot.llm.prompts import SYSTEM_PROMPT, staff_post_prompt


class LLMError(RuntimeError):
    pass


class LLMClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._client = httpx.AsyncClient(timeout=settings.llm_timeout_seconds)

    async def close(self) -> None:
        await self._client.aclose()

    async def generate_staff_post(self, note: str) -> str:
        if not note.strip():
            raise LLMError("Заметка пуста")
        if self.settings.llm_provider == "ollama":
            return await self._ollama(note)
        return await self._openai(note)

    async def _ollama(self, note: str) -> str:
        response = await self._client.post(
            f"{self.settings.llm_base_url.rstrip('/')}/api/chat",
            json={
                "model": self.settings.llm_model,
                "stream": False,
                "think": False,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": staff_post_prompt(note)},
                ],
                "options": {"temperature": 0.75},
            },
        )
        return self._extract(response, ("message", "content"))

    async def _openai(self, note: str) -> str:
        headers: dict[str, str] = {}
        if self.settings.llm_api_key:
            headers["Authorization"] = f"Bearer {self.settings.llm_api_key.get_secret_value()}"
        response = await self._client.post(
            f"{self.settings.llm_base_url.rstrip('/')}/v1/chat/completions",
            headers=headers,
            json={
                "model": self.settings.llm_model,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": staff_post_prompt(note)},
                ],
                "temperature": 0.75,
            },
        )
        return self._extract(response, ("choices", 0, "message", "content"))

    @staticmethod
    def _extract(response: httpx.Response, path: tuple[str | int, ...]) -> str:
        try:
            response.raise_for_status()
            value: Any = response.json()
            for key in path:
                value = value[key]
            text = str(value).strip()
        except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as error:
            raise LLMError("Локальная LLM не ответила корректно") from error
        if not text:
            raise LLMError("Локальная LLM вернула пустой ответ")
        return text

