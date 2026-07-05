from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from echoforge.stages.musevault.audio_normalizer import normalize_project_audio


def main() -> None:
    parser = argparse.ArgumentParser(description="Normalize project audio to audio/source_audio.m4a.")
    parser.add_argument("--project", required=True)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    result = normalize_project_audio(args.project, force=args.force)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    raise SystemExit(0 if result.get("ok") else 1)


if __name__ == "__main__":
    main()
