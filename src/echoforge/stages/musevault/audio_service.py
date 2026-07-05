from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def find_audio(audio_dir: Path) -> Path | None:
    candidates: list[Path] = []
    for pattern in ("*.m4a", "*.mp3", "*.webm", "*.opus", "*.wav", "*.aac"):
        candidates.extend(audio_dir.glob(pattern))
    return max(candidates, key=lambda p: p.stat().st_mtime) if candidates else None


def download_audio(project_dir: Path, review: dict[str, Any]) -> dict[str, Any]:
    audio_dir = project_dir / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    status_path = audio_dir / "audio_status.json"
    url = str(review.get("youtube_url") or "").strip()

    if not url:
        result = {"ok": False, "status": "failed", "reason": "missing YouTube URL"}
        write_json(status_path, result)
        return result

    existing = find_audio(audio_dir)
    if existing and existing.stat().st_size > 0:
        result = {"ok": True, "status": "exists", "path": str(existing), "checked_at": now_iso()}
        write_json(status_path, result)
        return result

    try:
        import yt_dlp
    except Exception as exc:
        result = {"ok": False, "status": "failed", "reason": f"yt-dlp missing: {exc}"}
        write_json(status_path, result)
        return result

    options = {
        "format": "bestaudio[ext=m4a]/bestaudio/best",
        "outtmpl": str(audio_dir / "source_audio.%(ext)s"),
        "noplaylist": True,
        "retries": 3,
        "fragment_retries": 3,
    }

    try:
        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(url, download=True)
        downloaded = find_audio(audio_dir)
    except Exception as exc:
        result = {"ok": False, "status": "failed", "reason": str(exc), "checked_at": now_iso()}
        write_json(status_path, result)
        return result

    if not downloaded:
        result = {"ok": False, "status": "failed", "reason": "no downloaded audio found"}
        write_json(status_path, result)
        return result

    result = {
        "ok": True,
        "status": "downloaded",
        "path": str(downloaded),
        "youtube_url": url,
        "title": info.get("title") if isinstance(info, dict) else None,
        "duration": info.get("duration") if isinstance(info, dict) else None,
        "checked_at": now_iso(),
    }
    write_json(status_path, result)
    return result
