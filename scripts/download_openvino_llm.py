#!/usr/bin/env python3
"""Download an OpenVINO IR LLM for NPU (default: Qwen3.5-9B INT4).

Example:
  python scripts/download_openvino_llm.py
  python scripts/download_openvino_llm.py --model OpenVINO/Qwen3.5-4B-int4-ov --out models/qwen35-4b
"""

from __future__ import annotations

import argparse
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--model",
        default="OpenVINO/Qwen3.5-9B-int4-ov",
        help="Hugging Face model id (OpenVINO IR)",
    )
    parser.add_argument(
        "--out",
        default="models/Qwen3.5-9B-int4-ov",
        help="Local directory for the snapshot",
    )
    args = parser.parse_args()

    try:
        from huggingface_hub import snapshot_download
    except ImportError:
        raise SystemExit(
            "Нужен пакет huggingface_hub: pip install huggingface_hub"
        ) from None

    out = Path(args.out).expanduser().resolve()
    out.mkdir(parents=True, exist_ok=True)
    print(f"Downloading {args.model} -> {out}")
    snapshot_download(repo_id=args.model, local_dir=str(out))
    print("Done.")
    print()
    print("Для бота на хосте с NPU (.env):")
    print("  LLM_PROVIDER=openvino")
    print(f"  LLM_MODEL={out}")
    print("  LLM_DEVICE=NPU")
    print("  LLM_TIMEOUT_SECONDS=1800")
    print()
    print("Для Docker-бота + NPU на хосте:")
    print("  python scripts/run_openvino_llm_server.py --model", out)
    print("  LLM_PROVIDER=openai")
    print("  LLM_BASE_URL=http://host.docker.internal:8091")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
