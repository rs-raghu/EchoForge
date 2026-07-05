from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from echoforge.stages.verselock.timestamp_transfer import timestamp_transfer_sync


def main() -> None:
    parser = argparse.ArgumentParser(description="Transfer Whisper timestamps onto official lyrics.txt.")
    parser.add_argument("--project", required=True)
    parser.add_argument("--transcript", default=None)
    parser.add_argument("--lyrics", default=None)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--promote", action="store_true", help="Write final_synced_lyrics.* instead of candidate files.")
    parser.add_argument("--use-segments", action="store_true", help="Use Whisper segment timestamps instead of word-grouped timestamps.")
    args = parser.parse_args()
    result = timestamp_transfer_sync(
        args.project,
        transcript_path=args.transcript,
        lyrics_path=args.lyrics,
        force=args.force,
        promote=args.promote,
        use_segments=args.use_segments,
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))
    raise SystemExit(0 if result.get("ok") else 1)


if __name__ == "__main__":
    main()
