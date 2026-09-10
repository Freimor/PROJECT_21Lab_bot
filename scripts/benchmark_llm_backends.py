#!/usr/bin/env python3
"""Compare OpenVINO NPU vs Ollama on the same prompt."""

from __future__ import annotations

import json
import sys
import time
import urllib.request
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_SRC = _ROOT / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from lab21_bot.llm.openvino_backend import OpenVinoGenerateRequest, generate_sync

PROMPT = (
    "Напиши короткий пост для Telegram (3–4 предложения) о том, "
    "что в лаборатории открыта регистрация на курс Python для новичков. "
    "Тон дружелюбный, без markdown."
)
SYSTEM = "Ты помощник лаборатории Lab21. Отвечай по-русски, кратко и по делу."
MAX_NEW_TOKENS = 256

MODEL_NPU = _ROOT / "models" / "Qwen3-8B-int4-cw-ov"
OLLAMA_URL = "http://127.0.0.1:11434/api/chat"
OLLAMA_MODEL = "qwen3.5:9b"  # closest available to Qwen3-8B


def bench_npu() -> dict:
    print("\n=== OpenVINO NPU (Qwen3-8B-int4-cw-ov) ===")
    req = OpenVinoGenerateRequest(
        system=SYSTEM,
        user=PROMPT,
        model_path=str(MODEL_NPU),
        device="NPU",
        temperature=0.7,
        max_new_tokens=MAX_NEW_TOKENS,
    )
    t0 = time.perf_counter()
    text = generate_sync(req)
    elapsed = time.perf_counter() - t0
    words = len(text.split())
    return {
        "backend": "OpenVINO NPU",
        "model": "Qwen3-8B-int4-cw-ov",
        "elapsed_s": round(elapsed, 2),
        "chars": len(text),
        "words": words,
        "tok_per_s_est": round(words * 1.3 / elapsed, 2) if elapsed else 0,
        "preview": text[:300],
    }


def bench_ollama() -> dict:
    print(f"\n=== Ollama ({OLLAMA_MODEL}) ===")
    payload = json.dumps(
        {
            "model": OLLAMA_MODEL,
            "stream": False,
            "think": False,
            "messages": [
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": PROMPT},
            ],
            "options": {"temperature": 0.7, "num_predict": MAX_NEW_TOKENS},
        }
    ).encode()
    req = urllib.request.Request(
        OLLAMA_URL,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    t0 = time.perf_counter()
    with urllib.request.urlopen(req, timeout=600) as resp:
        data = json.loads(resp.read())
    elapsed = time.perf_counter() - t0
    text = data.get("message", {}).get("content", "")
    eval_count = data.get("eval_count") or 0
    eval_duration_ns = data.get("eval_duration") or 0
    tok_per_s = (
        round(eval_count / (eval_duration_ns / 1e9), 2) if eval_duration_ns else None
    )
    return {
        "backend": "Ollama CPU",
        "model": OLLAMA_MODEL,
        "elapsed_s": round(elapsed, 2),
        "chars": len(text),
        "words": len(text.split()),
        "eval_count": eval_count,
        "tok_per_s": tok_per_s,
        "preview": text[:300],
    }


def main() -> None:
    results = []
    for fn in (bench_npu, bench_ollama):
        try:
            results.append(fn())
        except Exception as exc:
            results.append({"backend": fn.__name__, "error": str(exc)})
            print(f"ERROR: {exc}")

    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    for r in results:
        print(json.dumps(r, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
