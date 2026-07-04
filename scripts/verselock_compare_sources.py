from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from echoforge.stages.verselock.lyrics_whisper_aligner import (
    load_lyrics_lines,
    load_segments,
    load_words,
    source_match_report,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare lyrics.txt with Whisper transcript for VerseLock fallback quality.")
    parser.add_argument("--project", required=True)
    args = parser.parse_args()
    project = Path(args.project)
    lyrics = project / "lyrics" / "lyrics.txt"
    transcript = project / "sync" / "whisper_advanced_transcript.json"
    if not lyrics.exists():
        raise SystemExit(f"Missing {lyrics}")
    if not transcript.exists():
        raise SystemExit(f"Missing {transcript}. Run whisper advanced first.")
    report = source_match_report(project, load_lyrics_lines(lyrics), load_words(transcript), load_segments(transcript))
    out = project / "sync" / "source_match_report.json"
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
