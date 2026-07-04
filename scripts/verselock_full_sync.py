from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from echoforge.stages.verselock.sync_runner import run_verselock_sync


def main() -> None:
    parser = argparse.ArgumentParser(description="VerseLock sync: reuse LRC or fall back to Whisper timestamp transfer.")
    parser.add_argument("--project", required=True)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--force-fallback", action="store_true", help="Ignore existing synced_lyrics.lrc and test Whisper fallback.")
    parser.add_argument("--model", default="medium", help="CPU recommendation: medium. Faster: small. Avoid large-v3 on CPU unless you can wait.")
    parser.add_argument("--compute-type", default="int8")
    parser.add_argument("--language", default=None)
    parser.add_argument("--beam-size", type=int, default=5)
    args = parser.parse_args()
    result = run_verselock_sync(
        args.project,
        force=args.force,
        force_fallback=args.force_fallback,
        model_size=args.model,
        compute_type=args.compute_type,
        language=args.language,
        beam_size=args.beam_size,
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))
    raise SystemExit(0 if result.get("ok") else 1)


if __name__ == "__main__":
    main()
