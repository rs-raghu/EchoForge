from __future__ import annotations

import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from echoforge.songscout import mark_song_status

TIMESTAMP_RE = re.compile(r"\[(\d{1,2}):(\d{2})(?:[.:](\d{1,3}))?\]")
METADATA_RE = re.compile(r"\[[a-zA-Z]+:.*?\]")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def get_audio_duration(audio_path: Path) -> float | None:
    """Read precise audio duration using ffprobe."""
    if not audio_path.exists():
        return None
    try:
        cmd = [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(audio_path),
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return float(res.stdout.strip())
    except Exception:
        return None


def timestamp_to_seconds(minutes: str, seconds: str, fraction: str | None) -> float:
    ms = 0
    if fraction:
        fraction = fraction[:3].ljust(3, "0")
        ms = int(fraction)
    return int(minutes) * 60 + int(seconds) + (ms / 1000.0)


def seconds_to_timestamp(seconds: float) -> str:
    total_ms = max(int(round(seconds * 1000)), 0)
    minutes = total_ms // 60000
    remaining = total_ms % 60000
    secs = remaining // 1000
    hundredths = (remaining % 1000) // 10
    return f"{minutes:02d}:{secs:02d}.{hundredths:02d}"


def parse_lrc_lines(raw_text: str, audio_duration: float | None = None) -> list[dict[str, Any]]:
    """Parse LRC content into line objects with computed start and end timestamps."""
    raw_lines: list[tuple[float, str]] = []

    for line in raw_text.splitlines():
        line = line.strip()
        if not line:
            continue
        matches = list(TIMESTAMP_RE.finditer(line))
        if not matches:
            continue

        text = TIMESTAMP_RE.sub("", line).strip()
        text = METADATA_RE.sub("", text).strip()
        if not text:
            continue

        for m in matches:
            try:
                start = timestamp_to_seconds(m.group(1), m.group(2), m.group(3))
                raw_lines.append((start, text))
            except ValueError:
                continue

    raw_lines.sort(key=lambda x: x[0])
    if not raw_lines:
        return []

    parsed: list[dict[str, Any]] = []
    total = len(raw_lines)

    for idx, (start, text) in enumerate(raw_lines):
        # Calculate smart end time
        if idx + 1 < total:
            next_start = raw_lines[idx + 1][0]
            # If gap between lines is long (> 6s), don't keep lyrics on screen
            end = min(next_start, start + 5.5)
        else:
            end = (
                min(start + 5.0, audio_duration)
                if audio_duration and audio_duration > start
                else start + 4.0
            )

        # Minimum display time of 0.8 seconds
        if end <= start:
            end = start + 1.2

        parsed.append(
            {
                "index": idx,
                "start_seconds": round(start, 3),
                "end_seconds": round(end, 3),
                "start_ms": int(round(start * 1000)),
                "end_ms": int(round(end * 1000)),
                "timestamp": f"[{seconds_to_timestamp(start)}]",
                "text": text,
            }
        )

    return parsed


def align_plain_text_with_whisper(
    plain_text: str, audio_path: Path
) -> list[dict[str, Any]]:
    """Fallback alignment using faster-whisper when only plain lyrics are available."""
    print("[*] Loading Whisper model (base) for audio alignment...")
    from faster_whisper import WhisperModel

    model = WhisperModel("base", device="cpu", compute_type="int8")
    segments, _ = model.transcribe(str(audio_path), word_timestamps=True)

    whisper_segments = list(segments)
    lines = [l.strip() for l in plain_text.splitlines() if l.strip()]
    if not lines or not whisper_segments:
        return []

    # Map text lines onto Whisper's timing segments
    aligned: list[dict[str, Any]] = []
    seg_idx = 0
    total_segs = len(whisper_segments)

    for idx, line in enumerate(lines):
        if seg_idx < total_segs:
            seg = whisper_segments[seg_idx]
            start = seg.start
            end = seg.end
            seg_idx += 1
        else:
            prev_end = aligned[-1]["end_seconds"] if aligned else 0.0
            start = prev_end + 0.5
            end = start + 3.0

        aligned.append(
            {
                "index": idx,
                "start_seconds": round(start, 3),
                "end_seconds": round(end, 3),
                "start_ms": int(round(start * 1000)),
                "end_ms": int(round(end * 1000)),
                "timestamp": f"[{seconds_to_timestamp(start)}]",
                "text": line,
            }
        )

    return aligned


def sync_project_lyrics(project_dir: Path, song_id: str | None = None) -> dict[str, Any]:
    """Execute Stage 3: produce canonical sync/final_synced_lyrics.json."""
    sync_dir = project_dir / "sync"
    sync_dir.mkdir(parents=True, exist_ok=True)

    audio_path = project_dir / "audio" / "source_audio.m4a"
    audio_duration = get_audio_duration(audio_path)

    lrc_path = project_dir / "lyrics" / "lyrics.lrc"
    txt_path = project_dir / "lyrics" / "lyrics.txt"

    lines: list[dict[str, Any]] = []
    mode = "none"

    if lrc_path.exists():
        print(f"[*] Fast path: Parsing existing synced lyrics ({lrc_path.name})...")
        lines = parse_lrc_lines(lrc_path.read_text(encoding="utf-8"), audio_duration)
        mode = "lrc_direct"
    elif txt_path.exists() and audio_path.exists():
        print(f"[*] Plain lyrics found. Running Whisper audio alignment...")
        lines = align_plain_text_with_whisper(txt_path.read_text(encoding="utf-8"), audio_path)
        mode = "whisper_aligned"
    else:
        print("[!] No lyrics or audio found to synchronize.")
        return {"ok": False, "mode": "missing_inputs"}

    if not lines:
        print("[!] Failed to generate any timed lyric lines.")
        return {"ok": False, "mode": "empty_lines"}

    # 1. Write final_synced_lyrics.lrc
    out_lrc = sync_dir / "final_synced_lyrics.lrc"
    lrc_content = "\n".join(f"{item['timestamp']} {item['text']}" for item in lines) + "\n"
    out_lrc.write_text(lrc_content, encoding="utf-8")

    # 2. Write final_synced_lyrics.json
    out_json = sync_dir / "final_synced_lyrics.json"
    payload = {
        "schema_version": 1,
        "created_at": now_iso(),
        "mode": mode,
        "audio_duration": audio_duration,
        "line_count": len(lines),
        "lines": lines,
    }
    out_json.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    # 3. Update project_state.json
    state_file = project_dir / "project_state.json"
    if state_file.exists():
        state = json.loads(state_file.read_text(encoding="utf-8"))
        state["status"] = "synced"
        state["sync_mode"] = mode
        state["line_count"] = len(lines)
        state["updated_at"] = now_iso()
        state_file.write_text(json.dumps(state, indent=2), encoding="utf-8")
        if not song_id:
            song_id = state.get("song_id")

    # 4. Mark song status in SQLite database
    if song_id:
        mark_song_status(song_id, "synced", project_dir=str(project_dir))

    print(f"    [OK] Synced {len(lines)} lines -> sync/final_synced_lyrics.json")
    return {"ok": True, "mode": mode, "line_count": len(lines)}