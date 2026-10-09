from __future__ import annotations

import json
import re
import subprocess
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def read_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def slug_clip_id(prefix: str, idx: int) -> str:
    return f"{prefix}_{idx:04d}"


def parse_timestamp(value: str) -> float:
    value = value.strip()
    parts = value.split(":")
    try:
        if len(parts) == 2:
            minutes = int(parts[0])
            seconds = float(parts[1])
            return minutes * 60 + seconds
        if len(parts) == 3:
            hours = int(parts[0])
            minutes = int(parts[1])
            seconds = float(parts[2])
            return hours * 3600 + minutes * 60 + seconds
    except Exception:
        return 0.0
    return 0.0


LRC_RE = re.compile(r"\[(\d{1,2}:\d{2}(?:\.\d{1,3})?)\](.*)")


def parse_lrc(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    raw: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        match = LRC_RE.search(line)
        if not match:
            continue
        text = match.group(2).strip()
        if not text:
            continue
        raw.append({"start": parse_timestamp(match.group(1)), "text": text})
    raw.sort(key=lambda x: x["start"])
    out: list[dict[str, Any]] = []
    for i, item in enumerate(raw):
        start = float(item["start"])
        next_start = float(raw[i + 1]["start"]) if i + 1 < len(raw) else start + 3.0
        end = max(start + 0.5, next_start - 0.05)
        out.append({"start": round(start, 3), "end": round(end, 3), "text": item["text"]})
    return out


def normalize_line(item: Any) -> dict[str, Any] | None:
    if isinstance(item, str) or not isinstance(item, dict):
        return None
    text = item.get("text") or item.get("line") or item.get("lyric") or item.get("content")
    if not text:
        return None
    start = item.get("start", item.get("start_seconds", item.get("start_time", item.get("time", item.get("timestamp")))))
    end = item.get("end", item.get("end_seconds", item.get("end_time")))
    try:
        start_f = float(start)
    except Exception:
        return None
    try:
        end_f = float(end) if end is not None else start_f + 3.0
    except Exception:
        end_f = start_f + 3.0
    return {"start": round(start_f, 3), "end": round(max(start_f + 0.35, end_f), 3), "text": str(text).strip()}


def extract_lines_from_json(data: Any) -> list[dict[str, Any]]:
    candidates: list[Any] = []
    if isinstance(data, list):
        candidates = data
    elif isinstance(data, dict):
        for key in ("lines", "lyrics", "items", "clips", "entries"):
            if isinstance(data.get(key), list):
                candidates = data[key]
                break
        if not candidates and isinstance(data.get("timeline"), dict):
            for key in ("lines", "lyrics", "items", "clips"):
                if isinstance(data["timeline"].get(key), list):
                    candidates = data["timeline"][key]
                    break

    lines = []
    for item in candidates:
        norm = normalize_line(item)
        if norm:
            lines.append(norm)
    lines.sort(key=lambda x: x["start"])

    for i, line in enumerate(lines):
        if i + 1 < len(lines):
            next_start = lines[i + 1]["start"]
            if line["end"] > next_start or line["end"] <= line["start"] + 0.35:
                line["end"] = round(max(line["start"] + 0.5, next_start - 0.05), 3)
    return lines


def get_audio_duration(audio_path: Path) -> float | None:
    if not audio_path.exists():
        return None
    try:
        out = subprocess.check_output(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=nokey=1:noprint_wrappers=1",
                str(audio_path),
            ],
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=20,
        ).strip()
        if out:
            return round(float(out), 3)
    except Exception:
        return None
    return None


def first_existing(paths: list[Path]) -> Path | None:
    for path in paths:
        if path.exists() and path.stat().st_size > 0:
            return path
    return None


def rel_to_project(project_dir: Path, path: Path | None) -> str | None:
    if not path:
        return None
    try:
        return str(path.relative_to(project_dir)).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")


def read_project_metadata(project_dir: Path) -> tuple[str, str]:
    state = read_json(project_dir / "project_state.json", {}) or {}
    review = read_json(project_dir / "metadata_review.json", {}) or {}
    manifest = read_json(project_dir / "asset_manifest.json", {}) or {}

    title = (
        review.get("display_title")
        or review.get("title")
        or state.get("title")
        or state.get("song_title")
        or manifest.get("title")
        or project_dir.name
    )
    artist = (
        review.get("display_artist")
        or review.get("artist")
        or state.get("artist")
        or state.get("artist_text")
        or manifest.get("artist")
        or ""
    )
    return str(title), str(artist)


def load_final_lines(project_dir: Path) -> list[dict[str, Any]]:
    final_json = project_dir / "sync" / "final_synced_lyrics.json"
    lines = extract_lines_from_json(read_json(final_json, None))
    if lines:
        return lines
    final_lrc = project_dir / "sync" / "final_synced_lyrics.lrc"
    return parse_lrc(final_lrc)


def make_v2_project(project_dir: str | Path, force: bool = False) -> dict[str, Any]:
    project_dir = Path(project_dir).resolve()
    editor_dir = project_dir / "editor"
    editor_json = editor_dir / "editor_project.json"

    existing = read_json(editor_json, None)
    if isinstance(existing, dict) and existing.get("schema") == "echoforge.webeditor.v2" and not force:
        return {
            "ok": True,
            "mode": "existing_v2",
            "project_dir": str(project_dir),
            "editor_project": str(editor_json),
            "duration": existing.get("project", {}).get("duration"),
            "clip_count": sum(len(t.get("clips", [])) for t in existing.get("tracks", [])),
        }

    if editor_json.exists():
        backup_dir = editor_dir / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        shutil.copy2(editor_json, backup_dir / f"{stamp}_editor_project_before_v2.json")

    audio = first_existing(
        [
            project_dir / "audio" / "source_audio.m4a",
            project_dir / "audio" / "source_audio.mp3",
            project_dir / "audio" / "source_audio.wav",
            project_dir / "audio" / "source_audio.webm",
            project_dir / "audio" / "source_audio.mp4",
        ]
    )
    background = first_existing(
        [
            project_dir / "images" / "video_background.jpg",
            project_dir / "images" / "video_background.png",
            project_dir / "images" / "background_source.jpg",
            project_dir / "images" / "background_source.png",
        ]
    )
    thumbnail = first_existing(
        [
            project_dir / "images" / "music_thumbnail.jpg",
            project_dir / "images" / "music_thumbnail.png",
        ]
    )

    lines = load_final_lines(project_dir)
    max_line_end = max((float(x.get("end", 0)) for x in lines), default=0.0)
    audio_duration = get_audio_duration(audio) if audio else None
    duration = round(max(audio_duration or 0, max_line_end + 2.0, 10.0), 3)
    title, artist = read_project_metadata(project_dir)

    lyric_clips: list[dict[str, Any]] = []
    for idx, line in enumerate(lines, start=1):
        lyric_clips.append(
            {
                "id": slug_clip_id("lyric", idx),
                "type": "text",
                "name": f"Lyric {idx}",
                "start": round(float(line["start"]), 3),
                "end": round(float(line["end"]), 3),
                "text": line["text"],
                "x": 960,
                "y": 540,
                "width": 1500,
                "height": 140,
                "rotation": 0,
                "style": {
                    "fontFamily": "Bernier",
                    "fontSize": 50,
                    "color": "#000000",
                    "backgroundColor": "transparent",
                    "bold": False,
                    "italic": False,
                    "align": "center",
                    "opacity": 1.0,
                    "strokeColor": "transparent",
                    "strokeWidth": 0,
                },
            }
        )

    project = {
        "schema": "echoforge.webeditor.v2",
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "project": {
            "title": title,
            "artist": artist,
            "duration": duration,
            "project_dir": str(project_dir),
        },
        "canvas": {"width": 1920, "height": 1080},
        "assets": {
            "audio": rel_to_project(project_dir, audio),
            "background": rel_to_project(project_dir, background),
            "thumbnail": rel_to_project(project_dir, thumbnail),
            "font_bernier": "assets/fonts/Bernier/Bernier-Regular.ttf",
        },
        "settings": {
            "fps": 30,
            "defaultLyricStyle": {
                "fontFamily": "Bernier",
                "fontSize": 50,
                "color": "#000000",
                "align": "center",
            },
        },
        "tracks": [
            {
                "id": "track_background",
                "name": "Background",
                "type": "image",
                "locked": False,
                "clips": [
                    {
                        "id": "background_0001",
                        "type": "image",
                        "name": "Video Background",
                        "start": 0,
                        "end": duration,
                        "asset": rel_to_project(project_dir, background),
                        "x": 960,
                        "y": 540,
                        "width": 1920,
                        "height": 1080,
                        "opacity": 1.0,
                    }
                ]
                if background
                else [],
            },
            {
                "id": "track_lyrics",
                "name": "Lyrics",
                "type": "text",
                "locked": False,
                "clips": lyric_clips,
            },
            {
                "id": "track_audio",
                "name": "Audio",
                "type": "audio",
                "locked": False,
                "clips": [
                    {
                        "id": "audio_0001",
                        "type": "audio",
                        "name": "Source Audio",
                        "start": 0,
                        "end": duration,
                        "asset": rel_to_project(project_dir, audio),
                        "volume": 1.0,
                    }
                ]
                if audio
                else [],
            },
        ],
    }

    write_json(editor_json, project)
    write_json(
        editor_dir / "prepare_v2_report.json",
        {
            "ok": True,
            "mode": "created_v2",
            "editor_project": str(editor_json),
            "duration": duration,
            "lyric_clip_count": len(lyric_clips),
            "audio": str(audio) if audio else None,
            "background": str(background) if background else None,
            "created_at": now_iso(),
        },
    )

    return {
        "ok": True,
        "mode": "created_v2",
        "project_dir": str(project_dir),
        "editor_project": str(editor_json),
        "duration": duration,
        "lyric_clip_count": len(lyric_clips),
        "audio": str(audio) if audio else None,
        "background": str(background) if background else None,
    }


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Prepare EchoForge WebEditor v2 project.")
    parser.add_argument("--project", required=True, help="Project directory.")
    parser.add_argument("--force", action="store_true", help="Rebuild V2 editor project.")
    args = parser.parse_args()

    result = make_v2_project(args.project, force=args.force)
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
