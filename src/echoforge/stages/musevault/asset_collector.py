from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from echoforge.stages.musevault.audio_service import download_audio
from echoforge.stages.musevault.audio_normalizer import normalize_project_audio
from echoforge.stages.musevault.background_maker import make_lyrics_video_background
from echoforge.stages.musevault.genius_lyrics import fetch_genius_lyrics
from echoforge.stages.musevault.image_service import collect_background_source, collect_music_thumbnail
from echoforge.stages.musevault.metadata_review import load_review, resolve_project_dir, review_metadata
from echoforge.stages.musevault.synced_lyrics_fetcher import fetch_synced_lyrics
from echoforge.stages.musevault.thumbnail_maker import make_upload_thumbnail


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def update_manifest(project_dir: Path, updates: dict[str, Any]) -> dict[str, Any]:
    path = project_dir / "asset_manifest.json"
    manifest = read_json(path) if path.exists() else {"schema_version": 1, "assets": {}, "folders": {}}
    manifest.setdefault("assets", {}).update(updates)
    manifest["updated_at"] = now_iso()
    write_json(path, manifest)
    return manifest


def update_project_state(project_dir: Path, stage: str, status: str) -> dict[str, Any]:
    path = project_dir / "project_state.json"
    state = read_json(path)
    state.setdefault("stages", {})[stage] = status
    state["current_stage"] = f"{stage}_{status}" if status != "running" else stage
    state["updated_at"] = now_iso()
    write_json(path, state)
    return state


def mark_song_status(project_dir: Path, state: dict[str, Any], status: str) -> None:
    song_id = state.get("song_id")
    if not song_id:
        return
    try:
        from echoforge.stages.songscout.database import mark_song_status as db_mark
        db_mark(str(song_id), status, project_dir=str(project_dir), note=f"MuseVault status: {status}")
    except Exception as exc:
        print(f"Warning: could not update SongScout DB status: {exc}")


def collect_assets(project: str | Path, *, popup: bool = False, auto_review: bool = False, force_review: bool = False) -> dict[str, Any]:
    project_dir = resolve_project_dir(project)

    review = load_review(project_dir)
    if review is None or force_review:
        review = review_metadata(project_dir, popup=popup, auto=auto_review, force=force_review)["review"]

    state = update_project_state(project_dir, "musevault", "running")

    synced = fetch_synced_lyrics(project_dir, review)
    if synced.get("found"):
        lyrics = {"ok": True, "source": "lrclib_synced", "found": True, "lyrics_path": synced.get("lyrics_path")}
    else:
        lyrics = fetch_genius_lyrics(project_dir, review)

    audio = download_audio(project_dir, review)
    audio_normalized = normalize_project_audio(project_dir)
    if audio_normalized.get("ok"):
        audio = {**audio, **audio_normalized, "download_details": audio}
    thumbnail = collect_music_thumbnail(project_dir, review)
    background_source = collect_background_source(project_dir, review)
    upload_thumbnail = make_upload_thumbnail(project_dir, review)
    video_background = make_lyrics_video_background(project_dir, review)

    manifest = update_manifest(project_dir, {
        "lyrics": {"status": "ready" if lyrics.get("found") else "missing", "source": lyrics.get("source"), "path": lyrics.get("lyrics_path"), "details": lyrics},
        "synced_lyrics": {"status": "ready" if synced.get("found") else "missing", "source": synced.get("source"), "lrc_path": synced.get("lrc_path"), "json_path": synced.get("json_path"), "details": synced},
        "audio": {"status": "ready" if audio.get("ok") else "failed", "path": audio.get("path"), "details": audio},
        "music_thumbnail": {"status": "ready" if thumbnail.get("ok") else "failed", "path": thumbnail.get("path"), "details": thumbnail},
        "background_source": {"status": "ready" if background_source.get("ok") else "failed", "path": background_source.get("path"), "details": background_source},
        "upload_thumbnail": {"status": "ready" if upload_thumbnail.get("ok") else "failed", "path": upload_thumbnail.get("path"), "details": upload_thumbnail},
        "video_background": {"status": "ready" if video_background.get("ok") else "failed", "path": video_background.get("path"), "details": video_background},
    })

    required_ok = all([audio.get("ok"), thumbnail.get("ok"), background_source.get("ok"), upload_thumbnail.get("ok"), video_background.get("ok")])
    lyric_ok = bool(lyrics.get("found") or synced.get("found"))
    final_status = "done" if required_ok and lyric_ok else "needs_review"

    state = update_project_state(project_dir, "musevault", final_status)
    if final_status == "done":
        mark_song_status(project_dir, state, "assets_ready")

    return {
        "ok": final_status == "done",
        "status": final_status,
        "project_dir": str(project_dir),
        "review": review,
        "results": {
            "synced_lyrics": synced,
            "lyrics": lyrics,
            "audio": audio,
            "music_thumbnail": thumbnail,
            "background_source": background_source,
            "upload_thumbnail": upload_thumbnail,
            "video_background": video_background,
        },
        "manifest": manifest,
    }
