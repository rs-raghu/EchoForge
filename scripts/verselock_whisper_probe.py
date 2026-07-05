from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from echoforge.stages.verselock.whisper_probe import run_whisper_probe


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a lightweight Whisper fallback probe for VerseLock.")
    parser.add_argument("--project", required=True)
    parser.add_argument("--model", default="tiny", choices=["tiny", "base", "small", "medium", "large", "large-v2", "large-v3"])
    parser.add_argument("--engine", default="auto", choices=["auto", "faster-whisper", "openai-whisper"])
    parser.add_argument("--language", default=None, help="Optional language code, e.g. en. Leave blank for auto-detect.")
    parser.add_argument("--device", default="cpu", choices=["cpu", "cuda"])
    parser.add_argument("--compute-type", default="int8")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    result = run_whisper_probe(
        args.project,
        model_size=args.model,
        engine=args.engine,
        language=args.language,
        device=args.device,
        compute_type=args.compute_type,
        force=args.force,
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))
    raise SystemExit(0 if result.get("ok") else 1)


if __name__ == "__main__":
    main()
