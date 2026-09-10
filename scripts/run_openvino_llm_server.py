#!/usr/bin/env python3
"""Minimal OpenAI-compatible server for OpenVINO GenAI on host NPU.

Use when the bot runs in Docker and needs the Windows host NPU:

  pip install 'lab21-bot[openvino]' fastapi uvicorn huggingface_hub
  python scripts/download_openvino_llm.py
  python scripts/run_openvino_llm_server.py --model models/Qwen3.5-9B-int4-ov

Bot .env:
  LLM_PROVIDER=openai
  LLM_BASE_URL=http://host.docker.internal:8091
  LLM_MODEL=qwen3.5-9b-npu
  LLM_TIMEOUT_SECONDS=1800
"""

from __future__ import annotations

import argparse
import sys
import time
import uuid
from pathlib import Path

# Allow running without installing the package editable when src is present
_ROOT = Path(__file__).resolve().parents[1]
_SRC = _ROOT / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from lab21_bot.llm.openvino_backend import OpenVinoGenerateRequest, generate_sync, ping_sync


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatCompletionRequest(BaseModel):
    model: str = "openvino"
    messages: list[ChatMessage]
    temperature: float = 0.7
    max_tokens: int = Field(default=1024, ge=16, le=8192)


def build_app(model_path: str, device: str, model_id: str) -> FastAPI:
    app = FastAPI(title="Lab21 OpenVINO LLM", version="0.1.0")

    @app.get("/health")
    def health() -> dict[str, object]:
        ok = ping_sync(model_path, device)
        return {"ok": ok, "device": device, "model_path": model_path}

    @app.get("/v1/models")
    def list_models() -> dict[str, object]:
        return {
            "object": "list",
            "data": [{"id": model_id, "object": "model", "owned_by": "openvino"}],
        }

    @app.post("/v1/chat/completions")
    def chat_completions(body: ChatCompletionRequest) -> dict[str, object]:
        system_parts: list[str] = []
        user_parts: list[str] = []
        for msg in body.messages:
            if msg.role == "system":
                system_parts.append(msg.content)
            elif msg.role == "user":
                user_parts.append(msg.content)
            elif msg.role == "assistant":
                user_parts.append(f"Assistant: {msg.content}")
        if not user_parts:
            raise HTTPException(status_code=400, detail="no user message")
        try:
            text = generate_sync(
                OpenVinoGenerateRequest(
                    system="\n\n".join(system_parts),
                    user="\n\n".join(user_parts),
                    model_path=model_path,
                    device=device,
                    temperature=body.temperature,
                    max_new_tokens=body.max_tokens,
                )
            )
        except Exception as error:
            raise HTTPException(status_code=500, detail=str(error)) from error
        return {
            "id": f"chatcmpl-{uuid.uuid4().hex[:12]}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": body.model or model_id,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": text},
                    "finish_reason": "stop",
                }
            ],
        }

    return app


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--model",
        default="models/Qwen3.5-9B-int4-ov",
        help="Path to OpenVINO IR directory",
    )
    parser.add_argument("--device", default="NPU", choices=["NPU", "CPU", "GPU"])
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8091)
    parser.add_argument("--model-id", default="qwen3.5-9b-npu")
    parser.add_argument(
        "--preload",
        action="store_true",
        help="Compile/load model at startup (first request otherwise)",
    )
    args = parser.parse_args()

    model_path = str(Path(args.model).expanduser().resolve())
    if args.preload:
        print(f"Preloading {model_path} on {args.device}...")
        if not ping_sync(model_path, args.device):
            raise SystemExit("Failed to load OpenVINO model")
        print("Ready.")

    try:
        import uvicorn
    except ImportError:
        raise SystemExit("pip install uvicorn fastapi") from None

    app = build_app(model_path, args.device, args.model_id)
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
