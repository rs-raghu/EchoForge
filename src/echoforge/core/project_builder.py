from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from echoforge.core.paths import APP_STATE_DIR, PROJECTS_DIR
from echoforge.core.storage import atomic_json, file_lock
from echoforge.stages.songscout.database import (
    get_all_songs,
    get_metadata,
    get_song,
    mark_song_status,
    set_metadata,
)
from echoforge.stages.songscout.selector import get_next_song

PROJECT_SUBDIRS = [
    "lyrics",
    "audio",
    "images",
    "sync",
    "renders",
    "upload",
]

STAGES = {
    "songscout": "done",
    "project_builder": "done",
    "musevault": "pending",
    "verselock": "pending",
    "webeditor": "pending",
    "renderer": "pending",
    "tubeharbor": "pending",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def slugify(value: Any, max_length: int = 48) -> str:
    text = str(value or "").strip().lower()
    text = text.replace("&", " and ")
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = re.sub(r"-+", "-", text).strip("-")
    if not text:
        text = "unknown"
    return text[:max_length].strip("-") or "unknown"


def project_number_from_name(name: str) -> int | None:
    match = re.match(r"^(\d{4})_", name)
    return int(match.group(1)) if match else None


def get_highest_existing_project_number() -> int:
    PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
    highest = 0
    for path in PROJECTS_DIR.iterdir():
        if not path.is_dir():
            continue
        number = project_number_from_name(path.name)
        if number is not None:
            highest = max(highest, number)
    return highest


def get_next_project_number() -> int:
    saved = get_metadata("next_project_number")
    if saved:
        try:
            number = int(saved)
            if number > 0:
                return number
        except ValueError:
            pass

    number = get_highest_existing_project_number() + 1
    set_metadata("next_project_number", number)
    return number


def advance_project_number(current_number: int) -> None:
    saved = get_metadata("next_project_number")
    try:
        saved_number = int(saved) if saved else 0
    except ValueError:
        saved_number = 0
    set_metadata("next_project_number", max(saved_number, current_number + 1))


def build_project_id(project_number: int, title: str, artist: str) -> str:
    title_slug = slugify(title, max_length=42)
    artist_slug = slugify(artist, max_length=42)
    return f"{project_number:04d}_{title_slug}_{artist_slug}"


def ensure_project_dirs(project_dir: Path) -> None:
    project_dir.mkdir(parents=True, exist_ok=True)
    for subdir in PROJECT_SUBDIRS:
        folder = project_dir / subdir
        folder.mkdir(parents=True, exist_ok=True)
        gitkeep = folder / ".gitkeep"
        if not gitkeep.exists():
            gitkeep.write_text("", encoding="utf-8")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    atomic_json(path, payload)


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def build_project_state(song: dict[str, Any], project_id: str, project_dir: Path) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "project_id": project_id,
        "song_id": song.get("id"),
        "title": song.get("title"),
        "artist": song.get("artist"),
        "rank": song.get("rank"),
        "youtube_url": song.get("youtube_url"),
        "thumbnail_url": song.get("thumbnail_url"),
        "project_dir": str(project_dir),
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "current_stage": "project_initialized",
        "stages": dict(STAGES),
        "notes": [],
    }


def build_asset_manifest(project_dir: Path) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "assets": {
            "audio": {
                "status": "pending",
                "source": None,
                "path": None,
            },
            "lyrics": {
                "status": "pending",
                "raw_path": None,
                "cleaned_path": None,
                "source": None,
            },
            "music_thumbnail": {
                "status": "pending",
                "source_url": None,
                "path": None,
            },
            "video_background": {
                "status": "pending",
                "source": "assets/backgrounds",
                "path": None,
            },
            "synced_lyrics": {
                "status": "pending",
                "json_path": None,
                "lrc_path": None,
            },
            "upload_thumbnail": {
                "status": "pending",
                "path": None,
            },
            "final_video": {
                "status": "pending",
                "path": None,
            },
        },
        "folders": {
            "lyrics": str(project_dir / "lyrics"),
            "audio": str(project_dir / "audio"),
            "images": str(project_dir / "images"),
            "sync": str(project_dir / "sync"),
            "renders": str(project_dir / "renders"),
            "upload": str(project_dir / "upload"),
        },
    }


def find_project_by_song_id(song_id: str) -> dict[str, Any] | None:
    PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
    for state_path in PROJECTS_DIR.glob("*/project_state.json"):
        try:
            state = read_json(state_path)
        except Exception:
            continue
        if state.get("song_id") == song_id:
            state["project_dir"] = str(state_path.parent)
            return state
    return None


def list_projects(limit: int = 20) -> list[dict[str, Any]]:
    PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
    projects: list[dict[str, Any]] = []
    for state_path in sorted(PROJECTS_DIR.glob("*/project_state.json"), reverse=True):
        try:
            state = read_json(state_path)
        except Exception:
            continue
        projects.append(
            {
                "project_id": state.get("project_id"),
                "song_id": state.get("song_id"),
                "title": state.get("title"),
                "artist": state.get("artist"),
                "current_stage": state.get("current_stage"),
                "project_dir": str(state_path.parent),
                "created_at": state.get("created_at"),
            }
        )
        if len(projects) >= limit:
            break
    return projects


def get_selected_projects_from_db(limit: int = 20) -> list[dict[str, Any]]:
    selected_statuses = ["selected", "assets_ready", "synced", "rendered", "uploaded"]
    out: list[dict[str, Any]] = []
    for status in selected_statuses:
        out.extend(get_all_songs(limit=limit, status=status))
        if len(out) >= limit:
            break
    return out[:limit]


def _init_project_for_song(song: dict[str, Any], *, allow_existing: bool = True) -> dict[str, Any]:
    if not song:
        raise ValueError("Cannot initialize project: song is empty.")

    song_id = str(song.get("id") or "").strip()
    title = str(song.get("title") or "").strip()
    artist = str(song.get("artist") or "").strip()

    if not song_id or not title or not artist:
        raise ValueError("Cannot initialize project: song must have id, title, and artist.")

    existing = find_project_by_song_id(song_id)
    if existing and allow_existing:
        project_dir = Path(existing["project_dir"])
        # Recover initialization interrupted between filesystem and DB updates.
        ensure_project_dirs(project_dir)
        if not (project_dir / "asset_manifest.json").exists():
            write_json(project_dir / "asset_manifest.json", build_asset_manifest(project_dir))
        current_song = get_song(song_id) or song
        if current_song.get("status", "new") in {"new", "failed"}:
            mark_song_status(song_id, "selected", project_dir=str(project_dir), note="Existing project initialization recovered")
        return {
            "ok": True,
            "created": False,
            "reused": True,
            "project_id": existing.get("project_id"),
            "project_dir": str(project_dir),
            "song": song,
        }

    project_number = max(get_next_project_number(), get_highest_existing_project_number() + 1)
    project_id = build_project_id(project_number, title, artist)
    project_dir = PROJECTS_DIR / project_id

    # Avoid accidental collision if folder exists but no state file exists.
    while project_dir.exists() and not (project_dir / "project_state.json").exists():
        project_number += 1
        project_id = build_project_id(project_number, title, artist)
        project_dir = PROJECTS_DIR / project_id

    if project_dir.exists() and not allow_existing:
        raise FileExistsError(f"Project already exists: {project_dir}")

    ensure_project_dirs(project_dir)

    state = build_project_state(song, project_id, project_dir)
    manifest = build_asset_manifest(project_dir)

    write_json(project_dir / "project_state.json", state)
    write_json(project_dir / "asset_manifest.json", manifest)

    mark_song_status(
        song_id,
        "selected",
        project_dir=str(project_dir),
        note="Project initialized",
    )
    advance_project_number(project_number)

    return {
        "ok": True,
        "created": True,
        "reused": False,
        "project_id": project_id,
        "project_dir": str(project_dir),
        "song": song,
    }


def init_project_for_song(song, *, allow_existing=True):
    with file_lock(APP_STATE_DIR / "project_allocation.lock"):
        return _init_project_for_song(song, allow_existing=allow_existing)


def init_next_project(*, include_failed=False, allow_existing=True):
    # Select, allocate, persist and mark selected under the same OS-owned lock.
    with file_lock(APP_STATE_DIR / "project_allocation.lock"):
        song = get_next_song(include_failed=include_failed)
        if not song:
            return {"ok": False, "created": False, "reason": "No available song with status new found."}
        return _init_project_for_song(song, allow_existing=allow_existing)


def init_project_by_song_id(song_id, *, allow_existing=True):
    with file_lock(APP_STATE_DIR / "project_allocation.lock"):
        song = get_song(song_id)
        if not song:
            return {"ok": False, "created": False, "reason": f"Song not found: {song_id}"}
        return _init_project_for_song(song, allow_existing=allow_existing)
