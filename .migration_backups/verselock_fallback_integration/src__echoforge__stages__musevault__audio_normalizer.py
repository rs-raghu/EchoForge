from __future__ import annotations

import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

AUDIO_EXTENSIONS = [".m4a", ".mp3", ".wav", ".webm", ".aac", ".flac", ".mp4", ".mkv"]


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def find_source_media(project_dir: Path) -> Path | None:
    audio_dir = project_dir / "audio"
    if not audio_dir.exists():
        return None

    preferred = [
        audio_dir / "source_audio.m4a",
        audio_dir / "source_audio.mp3",
        audio_dir / "source_audio.wav",
        audio_dir / "source_audio.webm",
        audio_dir / "source_audio.mp4",
    ]
    for path in preferred:
        if path.exists() and path.is_file():
            return path

    for ext in AUDIO_EXTENSIONS:
        found = sorted(audio_dir.glob(f"*{ext}"))
        if found:
            return found[0]
    return None


def ensure_ffmpeg() -> str | None:
    return shutil.which("ffmpeg")


def normalize_project_audio(project: str | Path, *, force: bool = False, output_ext: str = ".m4a") -> dict[str, Any]:
    project_dir = Path(project)
    if not project_dir.exists():
        return {"ok": False, "reason": f"Project folder not found: {project_dir}"}

    ffmpeg = ensure_ffmpeg()
    if not ffmpeg:
        return {
            "ok": False,
            "reason": "ffmpeg is not installed or not available in PATH.",
            "fix": "Install FFmpeg and restart terminal, then run ffmpeg -version to confirm.",
            "project_dir": str(project_dir),
        }

    audio_dir = project_dir / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)

    source = find_source_media(project_dir)
    if not source:
        return {
            "ok": False,
            "reason": "No source media found in project/audio.",
            "expected": ["source_audio.m4a", "source_audio.mp3", "source_audio.wav", "source_audio.webm", "source_audio.mp4"],
            "project_dir": str(project_dir),
        }

    output_ext = output_ext if output_ext.startswith(".") else f".{output_ext}"
    if output_ext not in {".m4a", ".mp3", ".wav"}:
        return {"ok": False, "reason": f"Unsupported output extension: {output_ext}"}

    output = audio_dir / f"source_audio{output_ext}"
    if output.exists() and not force:
        result = {
            "ok": True,
            "mode": "normalize_project_audio",
            "reused_existing_output": True,
            "input": str(source),
            "output": str(output),
            "project_dir": str(project_dir),
        }
        update_reports(project_dir, result)
        return result

    if source.resolve() == output.resolve():
        result = {
            "ok": True,
            "mode": "normalize_project_audio",
            "already_audio_only_target": True,
            "input": str(source),
            "output": str(output),
            "project_dir": str(project_dir),
        }
        update_reports(project_dir, result)
        return result

    if output_ext == ".m4a":
        codec_args = ["-vn", "-c:a", "aac", "-b:a", "192k"]
    elif output_ext == ".mp3":
        codec_args = ["-vn", "-c:a", "libmp3lame", "-b:a", "192k"]
    else:
        codec_args = ["-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le"]

    cmd = [ffmpeg, "-y", "-i", str(source), *codec_args, str(output)]
    completed = subprocess.run(cmd, text=True, capture_output=True)

    if completed.returncode != 0 or not output.exists():
        return {
            "ok": False,
            "mode": "normalize_project_audio",
            "reason": "ffmpeg conversion failed",
            "input": str(source),
            "output": str(output),
            "stderr_tail": completed.stderr[-2000:],
            "project_dir": str(project_dir),
        }

    result = {
        "ok": True,
        "mode": "normalize_project_audio",
        "reused_existing_output": False,
        "input": str(source),
        "output": str(output),
        "output_size_bytes": output.stat().st_size,
        "project_dir": str(project_dir),
        "created_at": now_utc_iso(),
    }
    update_reports(project_dir, result)
    return result


def update_reports(project_dir: Path, result: dict[str, Any]) -> None:
    manifest_path = project_dir / "asset_manifest.json"
    manifest = read_json(manifest_path)
    manifest.setdefault("audio", {})["normalized_audio"] = {
        "ok": result.get("ok"),
        "input": result.get("input"),
        "output": result.get("output"),
        "updated_at": now_utc_iso(),
    }
    write_json(manifest_path, manifest)

    state_path = project_dir / "project_state.json"
    state = read_json(state_path)
    if state:
        state.setdefault("stage_reports", {})["audio_normalizer"] = result
        state["updated_at"] = now_utc_iso()
        write_json(state_path, state)
