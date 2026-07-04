from __future__ import annotations

import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

AUDIO_NAMES = [
    "source_audio.m4a",
    "source_audio.mp3",
    "source_audio.wav",
    "source_audio.webm",
    "source_audio.mp4",
]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def find_source_audio(project_dir: str | Path) -> Path | None:
    project_dir = Path(project_dir)
    audio_dir = project_dir / "audio"
    for name in AUDIO_NAMES:
        p = audio_dir / name
        if p.exists() and p.is_file():
            return p
    for p in sorted(audio_dir.glob("source_audio.*")):
        if p.is_file():
            return p
    return None


def normalize_project_audio(project_dir: str | Path, *, force: bool = False) -> dict[str, Any]:
    """Guarantee project/audio/source_audio.m4a exists.

    yt-dlp may download source_audio.mp4 or webm depending on availability.
    VerseLock and render stages should consume source_audio.m4a consistently.
    """
    project_dir = Path(project_dir)
    audio_dir = project_dir / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    status_path = audio_dir / "audio_normalization_status.json"
    target = audio_dir / "source_audio.m4a"

    source = find_source_audio(project_dir)
    if not source:
        result = {
            "ok": False,
            "stage": "audio_normalization",
            "reason": "No source_audio file found in project/audio.",
            "source": None,
            "target": str(target),
            "created_at": now_iso(),
        }
        _write_json(status_path, result)
        return result

    if target.exists() and source.resolve() == target.resolve() and not force:
        result = {
            "ok": True,
            "stage": "audio_normalization",
            "mode": "already_m4a",
            "source": str(source),
            "target": str(target),
            "path": str(target),
            "created_at": now_iso(),
        }
        _write_json(status_path, result)
        return result

    if target.exists() and not force:
        result = {
            "ok": True,
            "stage": "audio_normalization",
            "mode": "reused_existing_m4a",
            "source": str(source),
            "target": str(target),
            "path": str(target),
            "created_at": now_iso(),
        }
        _write_json(status_path, result)
        return result

    if shutil.which("ffmpeg") is None:
        result = {
            "ok": False,
            "stage": "audio_normalization",
            "reason": "ffmpeg not found in PATH. Cannot convert source audio to m4a.",
            "source": str(source),
            "target": str(target),
            "created_at": now_iso(),
        }
        _write_json(status_path, result)
        return result

    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(source),
        "-vn",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        str(target),
    ]
    try:
        completed = subprocess.run(cmd, check=True, capture_output=True, text=True)
        result = {
            "ok": True,
            "stage": "audio_normalization",
            "mode": "converted_to_m4a",
            "source": str(source),
            "target": str(target),
            "path": str(target),
            "created_at": now_iso(),
        }
    except subprocess.CalledProcessError as exc:
        result = {
            "ok": False,
            "stage": "audio_normalization",
            "reason": "ffmpeg failed while converting source audio to m4a.",
            "source": str(source),
            "target": str(target),
            "returncode": exc.returncode,
            "stderr": exc.stderr[-4000:] if exc.stderr else "",
            "created_at": now_iso(),
        }
    _write_json(status_path, result)
    return result
