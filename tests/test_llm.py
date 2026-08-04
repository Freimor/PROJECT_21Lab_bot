import httpx

from lab21_bot.config import Settings
from lab21_bot.llm.client import LLMClient


def settings(provider: str) -> Settings:
    return Settings(
        telegram_bot_token="token",
        bootstrap_magister_id=1,
        main_channel_id=-1001,
        staff_chat_id=-1002,
        llm_provider=provider,
        llm_base_url="http://llm.test",
        llm_model="test-model",
    )


async def test_ollama_adapter_uses_local_chat_api() -> None:
    async def responder(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/chat"
        assert b"test-model" in request.content
        return httpx.Response(200, json={"message": {"content": "Готовый пост"}})

    client = LLMClient(settings("ollama"))
    await client._client.aclose()
    client._client = httpx.AsyncClient(transport=httpx.MockTransport(responder))
    try:
        assert await client.generate_staff_post("Починили блок питания") == "Готовый пост"
    finally:
        await client.close()


async def test_openai_compatible_adapter() -> None:
    async def responder(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/chat/completions"
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "Черновик vLLM"}}]},
        )

    client = LLMClient(settings("openai"))
    await client._client.aclose()
    client._client = httpx.AsyncClient(transport=httpx.MockTransport(responder))
    try:
        assert await client.generate_staff_post("Напечатали корпус") == "Черновик vLLM"
    finally:
        await client.close()
