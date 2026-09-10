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


async def test_openvino_adapter_uses_backend(monkeypatch) -> None:
    from lab21_bot.llm import openvino_backend

    calls: list[object] = []

    def fake_generate(req: openvino_backend.OpenVinoGenerateRequest) -> str:
        calls.append(req)
        assert req.device == "NPU"
        assert req.model_path.endswith("Qwen3.5-9B-int4-ov")
        assert req.max_new_tokens == 256
        return "<b>Черновик NPU</b>"

    monkeypatch.setattr(openvino_backend, "generate_sync", fake_generate)

    cfg = Settings(
        telegram_bot_token="token",
        bootstrap_magister_id=1,
        main_channel_id=-1001,
        staff_chat_id=-1002,
        llm_provider="openvino",
        llm_model=r"C:\models\Qwen3.5-9B-int4-ov",
        llm_device="NPU",
        llm_timeout_seconds=600,
        llm_max_new_tokens=256,
    )
    client = LLMClient(cfg)
    try:
        assert await client.generate_staff_post("Починили блок питания") == "<b>Черновик NPU</b>"
        assert len(calls) == 1
        assert calls[0].model_path.endswith("Qwen3.5-9B-int4-ov")
    finally:
        await client.close()


def test_llm_provider_accepts_openvino() -> None:
    cfg = Settings(
        telegram_bot_token="token",
        bootstrap_magister_id=1,
        main_channel_id=-1001,
        staff_chat_id=-1002,
        llm_provider="openvino",
        llm_model="/models/qwen",
        llm_device="npu",
    )
    assert cfg.llm_provider == "openvino"
    assert cfg.llm_device == "NPU"