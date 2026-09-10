"""OpenVINO GenAI backend for local NPU/CPU/GPU inference.

Optional dependency: pip install 'lab21-bot[openvino]'
(or openvino + openvino-genai + openvino-tokenizers).
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_lock = threading.Lock()
_pipeline: Any | None = None
_pipeline_key: tuple[str, str] | None = None


@dataclass(frozen=True, slots=True)
class OpenVinoGenerateRequest:
    system: str
    user: str
    model_path: str
    device: str
    temperature: float
    max_new_tokens: int


def _import_genai() -> Any:
    try:
        import openvino_genai as ov_genai
    except ImportError as error:
        raise RuntimeError(
            "OpenVINO GenAI не установлен. "
            "На хосте с NPU: pip install 'lab21-bot[openvino]' "
            "(или openvino openvino-genai openvino-tokenizers)"
        ) from error
    return ov_genai


def _resolve_model_dir(model_path: str) -> Path:
    path = Path(model_path).expanduser()
    if not path.exists():
        raise RuntimeError(f"Каталог модели OpenVINO не найден: {path}")
    if path.is_file():
        path = path.parent
    # Prefer directory that contains openvino IR / genai config
    if (path / "openvino_model.xml").exists() or (path / "config.json").exists():
        return path
    return path


def get_pipeline(model_path: str, device: str) -> Any:
    """Load (or reuse) LLMPipeline for the given model/device."""
    global _pipeline, _pipeline_key
    ov_genai = _import_genai()
    resolved = str(_resolve_model_dir(model_path).resolve())
    device_norm = device.strip().upper() or "NPU"
    key = (resolved, device_norm)
    with _lock:
        if _pipeline is not None and _pipeline_key == key:
            return _pipeline
        # Drop previous pipeline before loading another device/model
        _pipeline = None
        _pipeline_key = None
        pipe = ov_genai.LLMPipeline(resolved, device_norm)
        _pipeline = pipe
        _pipeline_key = key
        return pipe


def generate_sync(req: OpenVinoGenerateRequest) -> str:
    """Blocking generation; call via asyncio.to_thread from async code."""
    ov_genai = _import_genai()
    pipe = get_pipeline(req.model_path, req.device)

    gen_kwargs: dict[str, Any] = {
        "max_new_tokens": max(16, int(req.max_new_tokens)),
    }
    # Temperature 0 → greedy; GenAI accepts float
    temp = float(req.temperature)
    if temp <= 0:
        gen_kwargs["temperature"] = 0.0
        gen_kwargs["do_sample"] = False
    else:
        gen_kwargs["temperature"] = temp

    system = (req.system or "").strip()
    user = (req.user or "").strip()
    if not user:
        raise RuntimeError("Пустой user-промпт для OpenVINO")

    with _lock:
        # Prefer chat API when available (Qwen instruct templates).
        start_chat = getattr(pipe, "start_chat", None)
        finish_chat = getattr(pipe, "finish_chat", None)
        try:
            if callable(start_chat) and callable(finish_chat):
                start_chat()
                try:
                    if system:
                        # Some GenAI builds accept system via set_chat_template /
                        # first message; fold into user if needed.
                        prompt = f"{system}\n\n{user}"
                    else:
                        prompt = user
                    result = pipe.generate(prompt, **gen_kwargs)
                finally:
                    finish_chat()
            else:
                prompt = f"{system}\n\n{user}" if system else user
                result = pipe.generate(prompt, **gen_kwargs)
        except TypeError:
            # Older GenAI: GenerationConfig object instead of kwargs
            config = ov_genai.GenerationConfig()
            config.max_new_tokens = gen_kwargs["max_new_tokens"]
            if "temperature" in gen_kwargs:
                config.temperature = gen_kwargs["temperature"]
            prompt = f"{system}\n\n{user}" if system else user
            result = pipe.generate(prompt, config)

    text = result if isinstance(result, str) else str(result)
    return text.strip()


def ping_sync(model_path: str, device: str) -> bool:
    try:
        get_pipeline(model_path, device)
        return True
    except Exception:
        return False


def reset_pipeline() -> None:
    """Test helper: drop cached pipeline."""
    global _pipeline, _pipeline_key
    with _lock:
        _pipeline = None
        _pipeline_key = None
