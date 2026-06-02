"""Application service layer for the local EchoForge Web Studio."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from echoforge.database import db_manager

from .state import CHECKLIST, action_key_for_state, get_state_meta

ROOT_DIR = Path(__file__).resolve().parents[2]
WORKSPACES_DIR = ROOT_DIR / "workspaces"
LOG_FILE = ROOT_DIR / "logs" / "echoforge.log"
_INIT_LOCK = threading.Lock()
_INITIALIZED = False
_JOB_LOCK = threading.Lock()
_JOB_THREADS: dict[int, threading.Thread] = {}

DEFAULT_APP_SETTINGS = {
    "theme": "dark",
    "defaultCountry": "US",
    "defaultPrivacy": "private",
    "autosaveSeconds": 2,
    "renderQuality": "standard",
    "previewResolution": "720p",
    "workspaceRoot": str(WORKSPACES_DIR),
}

DEFAULT_TEMPLATES = [
    {
        "name": "Minimal Center Lyrics",
        "description": "Clean centered lyric video with calm fades.",
        "aspectRatio": "16:9",
        "settings": {
            "template": "minimal_center",
            "aspectRatio": "16:9",
            "resolution": "1080p",
            "fps": 30,
            "backgroundType": "solid",
            "backgroundColor": "#111111",
            "fontFamily": "Inter",
            "fontSize": 64,
            "textColor": "#ffffff",
            "highlightColor": "#ffd966",
            "animation": "fade",
            "textPosition": "center",
            "watermark": True,
        },
        "isDefault": True,
    },
    {
        "name": "Karaoke Highlight",
        "description": "Word-level highlight styling for timestamped lyrics.",
        "aspectRatio": "16:9",
        "settings": {
            "template": "karaoke_highlight",
            "aspectRatio": "16:9",
            "resolution": "1080p",
            "fps": 30,
            "backgroundType": "gradient",
            "backgroundColor": "#101214",
            "fontFamily": "Inter",
            "fontSize": 60,
            "textColor": "#f5f7fa",
            "highlightColor": "#51d18d",
            "animation": "word_by_word",
            "textPosition": "center",
            "watermark": True,
        },
        "isDefault": False,
    },
    {
        "name": "Dark Cinematic",
        "description": "High-contrast look with lower-third lyrics.",
        "aspectRatio": "16:9",
        "settings": {
            "template": "dark_cinematic",
            "aspectRatio": "16:9",
            "resolution": "1080p",
            "fps": 30,
            "backgroundType": "solid",
            "backgroundColor": "#07090c",
            "fontFamily": "Georgia",
            "fontSize": 56,
            "textColor": "#f2f0e8",
            "highlightColor": "#d4af37",
            "animation": "slide_up",
            "textPosition": "bottom",
            "watermark": False,
        },
        "isDefault": False,
    },
    {
        "name": "Vertical Shorts",
        "description": "Tall layout optimized for short-form uploads.",
        "aspectRatio": "9:16",
        "settings": {
            "template": "vertical_shorts",
            "aspectRatio": "9:16",
            "resolution": "1080p",
            "fps": 30,
            "backgroundType": "gradient",
            "backgroundColor": "#15231f",
            "fontFamily": "Inter",
            "fontSize": 68,
            "textColor": "#ffffff",
            "highlightColor": "#7dd3fc",
            "animation": "scale_pop",
            "textPosition": "center",
            "watermark": True,
        },
        "isDefault": False,
    },
    {
        "name": "Neon Glow",
        "description": "Bright accent look for energetic lyric videos.",
        "aspectRatio": "1:1",
        "settings": {
            "template": "neon_glow",
            "aspectRatio": "1:1",
            "resolution": "1080p",
            "fps": 30,
            "backgroundType": "solid",
            "backgroundColor": "#0b0f1a",
            "fontFamily": "Inter",
            "fontSize": 58,
            "textColor": "#f8fbff",
            "highlightColor": "#ff4fd8",
            "animation": "karaoke_fill",
            "textPosition": "center",
            "watermark": True,
        },
        "isDefault": False,
    },
]


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(db_manager.DB_PATH, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    return conn


def init_web_studio() -> None:
    """Create the existing core schema and the new Web Studio support tables."""
    global _INITIALIZED
    if _INITIALIZED:
        return
    with _INIT_LOCK:
        if _INITIALIZED:
            return
        db_manager.init_db()
        with _connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_id TEXT,
                    job_type TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    progress INTEGER NOT NULL DEFAULT 0,
                    message TEXT,
                    started_at TEXT,
                    finished_at TEXT,
                    error_message TEXT,
                    log_path TEXT,
                    cancel_requested INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS project_files (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_id TEXT NOT NULL,
                    file_type TEXT NOT NULL,
                    file_path TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS lyrics_versions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_id TEXT NOT NULL,
                    file_path TEXT NOT NULL,
                    version_label TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    created_by TEXT NOT NULL DEFAULT 'web_studio',
                    notes TEXT,
                    is_approved INTEGER NOT NULL DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS timestamp_versions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_id TEXT NOT NULL,
                    file_path TEXT NOT NULL,
                    version_label TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    created_by TEXT NOT NULL DEFAULT 'web_studio',
                    notes TEXT,
                    is_approved INTEGER NOT NULL DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS templates (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    aspect_ratio TEXT,
                    settings_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    is_default INTEGER NOT NULL DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_id TEXT,
                    event_type TEXT NOT NULL,
                    message TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS upload_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_id TEXT NOT NULL,
                    youtube_url TEXT,
                    privacy TEXT NOT NULL DEFAULT 'private',
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                """
            )
            _seed_default_templates(conn)
            conn.commit()
        _INITIALIZED = True


def health() -> dict[str, Any]:
    init_web_studio()
    return {
        "ok": True,
        "app": "EchoForge Web Studio",
        "database": str(db_manager.DB_PATH),
        "workspaceRoot": str(WORKSPACES_DIR),
        "time": datetime.now().isoformat(timespec="seconds"),
    }


def dashboard() -> dict[str, Any]:
    projects = list_projects(limit=200)
    counts: dict[str, int] = {}
    for project in projects:
        counts[project["rawState"]] = counts.get(project["rawState"], 0) + 1

    cards = [
        {"key": "discovered", "label": "Songs discovered", "value": counts.get("DISCOVERED", 0), "tone": "neutral"},
        {
            "key": "lyricsReview",
            "label": "Lyrics review",
            "value": counts.get("LYRICS_REVIEW_PENDING", 0),
            "tone": "warning",
        },
        {
            "key": "syncReview",
            "label": "Sync ready",
            "value": counts.get("ASSETS_READY", 0),
            "tone": "success",
        },
        {
            "key": "readyUpload",
            "label": "Ready to upload",
            "value": counts.get("PREVIEW_PENDING", 0),
            "tone": "review",
        },
        {"key": "failed", "label": "Failed jobs", "value": counts.get("FAILED", 0), "tone": "danger"},
    ]

    active = [
        project
        for project in projects
        if project["rawState"] not in {"DISCOVERED", "PUBLISHED", "DISCARDED", "UNAVAILABLE"}
    ]
    queue = [project for project in projects if project["rawState"] == "DISCOVERED"]
    recent = projects[:8]

    return {
        "summary": cards,
        "activeProjects": active[:8],
        "queue": queue[:10],
        "recentProjects": recent,
        "stateCounts": counts,
        "logs": read_logs(limit=30),
    }


def list_projects(limit: int = 100, state: str | None = None) -> list[dict[str, Any]]:
    init_web_studio()
    query = "SELECT * FROM songs"
    params: list[Any] = []
    if state:
        query += " WHERE current_macro_state=?"
        params.append(state)
    query += " ORDER BY updated_at DESC LIMIT ?"
    params.append(limit)

    with _connect() as conn:
        rows = conn.execute(query, tuple(params)).fetchall()
    return [_project_from_row(row) for row in rows]


def get_project(project_id: str) -> dict[str, Any]:
    init_web_studio()
    row = _song_row(project_id)
    if row is None:
        raise KeyError(project_id)
    project = _project_from_row(row)
    project["files"] = list_project_files(project_id)
    project["logs"] = read_logs(project_id=project_id, limit=80)
    return project


def create_project(payload: dict[str, Any]) -> dict[str, Any]:
    init_web_studio()
    title = str(payload.get("title") or "Untitled Project").strip()
    artist = str(payload.get("artist") or "Unknown Artist").strip()
    source_url = str(payload.get("sourceUrl") or payload.get("source_url") or "").strip()
    video_id = str(payload.get("videoId") or payload.get("video_id") or "").strip()
    if not video_id:
        video_id = _extract_video_id(source_url) or _manual_project_id(title, artist, source_url)
    if not source_url and not video_id.startswith("manual_"):
        source_url = f"https://www.youtube.com/watch?v={video_id}"

    workspace = WORKSPACES_DIR / video_id
    workspace.mkdir(parents=True, exist_ok=True)

    with _connect() as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO songs
                (video_id, title, artist, url, current_macro_state, current_micro_state,
                 target_macro_state, workspace_dir, updated_at)
            VALUES (?, ?, ?, ?, 'DISCOVERED', 'IDLE', 'STAGED', ?, CURRENT_TIMESTAMP)
            """,
            (video_id, title, artist, source_url, str(workspace)),
        )
        conn.execute(
            """
            UPDATE songs
            SET title=?, artist=?, url=?, workspace_dir=?, updated_at=CURRENT_TIMESTAMP
            WHERE video_id=?
            """,
            (title, artist, source_url, str(workspace), video_id),
        )
        conn.commit()
    _record_event(video_id, "project_created", f"Project created: {title}")
    return get_project(video_id)


def run_discovery(limit: int = 20, country: str = "US", force: bool = False) -> dict[str, Any]:
    init_web_studio()
    from echoforge.discovery import chart_scraper

    age, stale = db_manager.get_last_scrape_info()
    if not stale and not force:
        return {
            "added": 0,
            "skipped": True,
            "message": f"Charts were scraped {age}; pass force=true to refresh now.",
        }
    songs = chart_scraper.scrape_top_charts(limit=limit, country=country)
    added = db_manager.add_discovered_songs(songs)
    if songs:
        db_manager.mark_chart_scraped()
    return {"added": added, "count": len(songs), "songs": songs}


def stage_next_project() -> dict[str, Any] | None:
    init_web_studio()
    song = db_manager.pop_next_queued_song()
    if not song:
        return None
    _ensure_workspace(song["video_id"], song.get("workspace_dir"))
    _record_event(song["video_id"], "project_staged", "Project staged from queue")
    return get_project(song["video_id"])


def run_project_action(project_id: str, action: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    init_web_studio()
    payload = payload or {}
    song = db_manager.get_song(project_id)
    if not song:
        raise KeyError(project_id)

    if action == "stage":
        db_manager.update_state(project_id, macro="STAGED", micro="IDLE", workspace_dir=str(_ensure_workspace(project_id)))
        db_manager.set_target_state(project_id, "STAGED")
        _record_event(project_id, "project_staged", "Project staged")

    elif action in {"run_full", "run-full"}:
        _resume_if_paused_or_discovered(project_id, song)
        db_manager.set_target_state(project_id, "PUBLISHED")
        _record_event(project_id, "pipeline_started", "Pipeline target set to PUBLISHED")

    elif action in {"assets_only", "assets-only"}:
        _resume_if_paused_or_discovered(project_id, song)
        db_manager.set_target_state(project_id, "ASSETS_READY")
        _record_event(project_id, "pipeline_started", "Pipeline target set to ASSETS_READY")

    elif action in {"continue_video", "continue-video"}:
        db_manager.set_target_state(project_id, "PUBLISHED")
        _record_event(project_id, "video_continued", "Final render/upload flow resumed")

    elif action in {"approve_lyrics", "approve-lyrics"}:
        _backup_lyrics_if_present(project_id, song)
        db_manager.update_state(project_id, macro="LYRICS_APPROVED", micro="IDLE")
        _record_event(project_id, "lyrics_approved", "Lyrics approved")

    elif action in {"approve_sync", "approve-sync"}:
        approve_timestamps(project_id, payload)

    elif action in {"approve_video", "approve-video"}:
        db_manager.update_state(project_id, macro="VIDEO_APPROVED", micro="IDLE")
        db_manager.set_target_state(project_id, "PUBLISHED")
        _record_event(project_id, "video_approved", "Video approved for upload")

    elif action == "discard":
        db_manager.update_state(project_id, macro="DISCARDED", micro="IDLE")
        _record_event(project_id, "project_discarded", "Project discarded")

    elif action == "abort":
        db_manager.request_abort(project_id)
        _record_event(project_id, "abort_requested", "Abort requested")

    elif action == "pause":
        db_manager.set_target_state(project_id, "PAUSED")
        _record_event(project_id, "pause_requested", "Pause requested at next checkpoint")

    elif action == "retry":
        target = str(payload.get("target") or song.get("target_macro_state") or "PUBLISHED")
        retry_state = _retry_macro_from_workspace(song)
        db_manager.update_state(project_id, macro=retry_state, micro="IDLE")
        db_manager.set_target_state(project_id, target)
        _record_event(project_id, "retry_started", f"Retry from {retry_state} toward {target}")

    else:
        raise ValueError(f"Unknown project action: {action}")

    return get_project(project_id)


def get_lyrics(project_id: str) -> dict[str, Any]:
    init_web_studio()
    row = _song_row(project_id)
    if row is None:
        raise KeyError(project_id)

    workspace = _workspace_path(project_id, row["workspace_dir"])
    draft_path = _lyrics_draft_path(workspace)
    active_path = _lyrics_active_path(workspace)
    read_path = draft_path if draft_path.exists() else active_path
    content = read_path.read_text(encoding="utf-8", errors="replace") if read_path.exists() else ""
    lines = _parse_lyric_lines(content)
    warnings = _lyrics_warnings(lines)
    return {
        "projectId": project_id,
        "source": "draft" if draft_path.exists() else "current",
        "sourcePath": str(read_path) if read_path.exists() else "",
        "activePath": str(active_path),
        "draftPath": str(draft_path),
        "format": "lrc" if _content_has_timestamps(lines) else "text",
        "hasDraft": draft_path.exists(),
        "rawText": content,
        "lines": lines,
        "warnings": warnings,
        "versions": list_lyrics_versions(project_id),
    }


def save_lyrics(project_id: str, payload: dict[str, Any], draft: bool = False) -> dict[str, Any]:
    init_web_studio()
    row = _song_row(project_id)
    if row is None:
        raise KeyError(project_id)

    workspace = _workspace_path(project_id, row["workspace_dir"])
    workspace.mkdir(parents=True, exist_ok=True)
    lines = _lyrics_lines_from_payload(payload)
    content = _render_lyrics_lines(lines)

    if draft:
        target = _lyrics_draft_path(workspace)
        _atomic_write_text(target, content)
        _record_event(project_id, "lyrics_draft_saved", "Lyrics draft saved")
    else:
        target = _lyrics_target_path(workspace, lines)
        _backup_file_version(project_id, target, approved=False, notes="Backup before lyrics save")
        _atomic_write_text(target, content)
        if bool(payload.get("clearDraft", True)):
            draft_path = _lyrics_draft_path(workspace)
            if draft_path.exists():
                draft_path.unlink()
        _record_event(project_id, "lyrics_saved", "Lyrics saved")

    return get_lyrics(project_id)


def approve_lyrics(project_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    init_web_studio()
    payload = payload or {}
    row = _song_row(project_id)
    if row is None:
        raise KeyError(project_id)

    workspace = _workspace_path(project_id, row["workspace_dir"])
    if payload.get("lines") or payload.get("text") is not None:
        save_lyrics(project_id, payload, draft=False)
    elif _lyrics_draft_path(workspace).exists():
        draft_content = _lyrics_draft_path(workspace).read_text(encoding="utf-8", errors="replace")
        save_lyrics(project_id, {"lines": _parse_lyric_lines(draft_content)}, draft=False)

    active_path = _lyrics_active_path(workspace)
    if active_path.exists():
        _backup_file_version(project_id, active_path, approved=True, notes="Approved lyrics version")

    db_manager.update_state(project_id, macro="LYRICS_APPROVED", micro="IDLE")
    _record_event(project_id, "lyrics_approved", "Lyrics approved")
    return get_lyrics(project_id)


def list_lyrics_versions(project_id: str) -> list[dict[str, Any]]:
    init_web_studio()
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT id, file_path, version_label, created_at, created_by, notes, is_approved
            FROM lyrics_versions
            WHERE project_id=?
            ORDER BY created_at DESC, id DESC
            LIMIT 50
            """,
            (project_id,),
        ).fetchall()
    return [
        {
            "id": row["id"],
            "filePath": row["file_path"],
            "versionLabel": row["version_label"],
            "createdAt": row["created_at"],
            "createdBy": row["created_by"],
            "notes": row["notes"],
            "isApproved": bool(row["is_approved"]),
        }
        for row in rows
    ]


def get_timestamps(project_id: str) -> dict[str, Any]:
    init_web_studio()
    row = _song_row(project_id)
    if row is None:
        raise KeyError(project_id)

    workspace = _workspace_path(project_id, row["workspace_dir"])
    draft_path = _timestamps_draft_path(workspace)
    active_path = _timestamps_active_path(workspace)
    read_path = draft_path if draft_path.exists() else active_path
    content = read_path.read_text(encoding="utf-8", errors="replace") if read_path.exists() else ""
    segments = _timestamp_segments_from_json(content) if content else []
    warnings = _timestamp_warnings(segments)
    return {
        "projectId": project_id,
        "source": "draft" if draft_path.exists() else "current",
        "sourcePath": str(read_path) if read_path.exists() else "",
        "activePath": str(active_path),
        "draftPath": str(draft_path),
        "hasDraft": draft_path.exists(),
        "segmentCount": len(segments),
        "duration": _timestamp_duration(segments),
        "segments": segments,
        "warnings": warnings,
        "versions": list_timestamp_versions(project_id),
    }


def save_timestamps(project_id: str, payload: dict[str, Any], draft: bool = False) -> dict[str, Any]:
    init_web_studio()
    row = _song_row(project_id)
    if row is None:
        raise KeyError(project_id)

    workspace = _workspace_path(project_id, row["workspace_dir"])
    workspace.mkdir(parents=True, exist_ok=True)
    segments = _timestamp_segments_from_payload(payload)
    content = _render_timestamp_segments(segments)

    if draft:
        target = _timestamps_draft_path(workspace)
        _atomic_write_text(target, content)
        _record_event(project_id, "timestamps_draft_saved", "Sync draft saved")
    else:
        target = _timestamps_active_path(workspace)
        _backup_timestamp_version(project_id, target, approved=False, notes="Backup before sync save")
        _atomic_write_text(target, content)
        if bool(payload.get("clearDraft", True)):
            draft_path = _timestamps_draft_path(workspace)
            if draft_path.exists():
                draft_path.unlink()
        _record_event(project_id, "timestamps_saved", "Sync timings saved")

    return get_timestamps(project_id)


def validate_timestamps(project_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    init_web_studio()
    row = _song_row(project_id)
    if row is None:
        raise KeyError(project_id)

    if payload and (payload.get("segments") is not None or payload.get("text") is not None):
        segments = _timestamp_segments_from_payload(payload)
    else:
        segments = get_timestamps(project_id)["segments"]

    return {
        "projectId": project_id,
        "segmentCount": len(segments),
        "duration": _timestamp_duration(segments),
        "segments": segments,
        "warnings": _timestamp_warnings(segments),
    }


def shift_timestamps(project_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    init_web_studio()
    row = _song_row(project_id)
    if row is None:
        raise KeyError(project_id)

    segments = (
        _timestamp_segments_from_payload(payload)
        if payload.get("segments") is not None
        else get_timestamps(project_id)["segments"]
    )
    delta = _coerce_seconds(payload.get("delta"), 0.0)
    scope = str(payload.get("scope") or "selected")
    segment_ids = {str(item) for item in payload.get("segmentIds", []) if item}
    start_index = int(payload.get("startIndex") or 1)

    shifted = []
    for segment in segments:
        should_shift = scope == "all"
        if scope == "selected":
            should_shift = not segment_ids or str(segment.get("id")) in segment_ids
        elif scope == "fromIndex":
            should_shift = int(segment.get("index") or 0) >= start_index

        if should_shift:
            shifted_words = []
            for word in segment.get("words", []):
                if not isinstance(word, dict):
                    continue
                shifted_words.append(
                    {
                        **word,
                        "start": round(max(0.0, _coerce_seconds(word.get("start"), 0.0) + delta), 3),
                        "end": round(max(0.0, _coerce_seconds(word.get("end"), 0.0) + delta), 3),
                    }
                )
            segment = {
                **segment,
                "start": round(max(0.0, float(segment["start"]) + delta), 3),
                "end": round(max(0.05, float(segment["end"]) + delta), 3),
                "words": shifted_words,
            }
            if segment["end"] <= segment["start"]:
                segment["end"] = round(segment["start"] + 0.05, 3)
        shifted.append(segment)

    return {
        "projectId": project_id,
        "segmentCount": len(shifted),
        "duration": _timestamp_duration(shifted),
        "segments": shifted,
        "warnings": _timestamp_warnings(shifted),
    }


def approve_timestamps(project_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    init_web_studio()
    payload = payload or {}
    row = _song_row(project_id)
    if row is None:
        raise KeyError(project_id)

    workspace = _workspace_path(project_id, row["workspace_dir"])
    if payload.get("segments") is not None or payload.get("text") is not None:
        save_timestamps(project_id, payload, draft=False)
    elif _timestamps_draft_path(workspace).exists():
        draft_content = _timestamps_draft_path(workspace).read_text(encoding="utf-8", errors="replace")
        save_timestamps(project_id, {"segments": _timestamp_segments_from_json(draft_content)}, draft=False)

    active_path = _timestamps_active_path(workspace)
    if active_path.exists():
        _backup_timestamp_version(project_id, active_path, approved=True, notes="Approved sync version")

    db_manager.update_state(project_id, macro="ASSETS_READY", micro="IDLE")
    _record_event(project_id, "timestamps_approved", "Sync timings approved")
    return get_timestamps(project_id)


def list_timestamp_versions(project_id: str) -> list[dict[str, Any]]:
    init_web_studio()
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT id, file_path, version_label, created_at, created_by, notes, is_approved
            FROM timestamp_versions
            WHERE project_id=?
            ORDER BY created_at DESC, id DESC
            LIMIT 50
            """,
            (project_id,),
        ).fetchall()
    return [
        {
            "id": row["id"],
            "filePath": row["file_path"],
            "versionLabel": row["version_label"],
            "createdAt": row["created_at"],
            "createdBy": row["created_by"],
            "notes": row["notes"],
            "isApproved": bool(row["is_approved"]),
        }
        for row in rows
    ]


def list_templates() -> list[dict[str, Any]]:
    init_web_studio()
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT id, name, aspect_ratio, settings_json, created_at, updated_at, is_default
            FROM templates
            ORDER BY is_default DESC, name ASC
            """
        ).fetchall()
    return [_template_from_row(row) for row in rows]


def get_project_design(project_id: str) -> dict[str, Any]:
    init_web_studio()
    row = _song_row(project_id)
    if row is None:
        raise KeyError(project_id)
    workspace = _workspace_path(project_id, row["workspace_dir"])
    design_path = _design_path(workspace)
    active = _read_json_file(design_path)
    if not active:
        default_template = next((template for template in list_templates() if template["isDefault"]), None)
        active = {
            "templateId": default_template["id"] if default_template else None,
            "templateName": default_template["name"] if default_template else "Minimal Center Lyrics",
            "settings": default_template["settings"] if default_template else DEFAULT_TEMPLATES[0]["settings"],
            "isSaved": False,
        }
    active.setdefault("projectId", project_id)
    active.setdefault("designPath", str(design_path))
    active.setdefault("renderPropsPath", str(_render_props_path(workspace)))
    return active


def save_project_design(project_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    init_web_studio()
    row = _song_row(project_id)
    if row is None:
        raise KeyError(project_id)
    workspace = _workspace_path(project_id, row["workspace_dir"])
    workspace.mkdir(parents=True, exist_ok=True)
    template_id = payload.get("templateId")
    template = _template_by_id(template_id) if template_id else None
    settings = payload.get("settings") if isinstance(payload.get("settings"), dict) else {}
    if template and not settings:
        settings = template["settings"]
    design = {
        "projectId": project_id,
        "templateId": template["id"] if template else template_id,
        "templateName": payload.get("templateName") or (template["name"] if template else "Custom"),
        "settings": _normalized_design_settings(settings),
        "isSaved": True,
        "updatedAt": datetime.now().isoformat(timespec="seconds"),
    }
    _atomic_write_text(_design_path(workspace), json.dumps(design, indent=2, ensure_ascii=False) + "\n")
    render_props = {
        "title": row["title"] or "Untitled Project",
        "artist": row["artist"] or "Unknown Artist",
        "design": design["settings"],
    }
    _atomic_write_text(_render_props_path(workspace), json.dumps(render_props, indent=2, ensure_ascii=False) + "\n")
    _record_event(project_id, "design_saved", f"Design saved: {design['templateName']}")
    return get_project_design(project_id)


def render_readiness(project_id: str) -> dict[str, Any]:
    init_web_studio()
    row = _song_row(project_id)
    if row is None:
        raise KeyError(project_id)
    workspace = _workspace_path(project_id, row["workspace_dir"])
    files = _workspace_flags(workspace)
    sync = get_timestamps(project_id) if files["timestamps"] or files["draftTimestamps"] else {"warnings": []}
    critical_sync_warnings = [warning for warning in sync["warnings"] if warning.get("severity") == "danger"]
    free_bytes = shutil.disk_usage(workspace if workspace.exists() else WORKSPACES_DIR).free
    checks = [
        {"key": "audio", "label": "Audio exists", "ok": files["audio"], "fix": "Run audio download"},
        {
            "key": "lyrics",
            "label": "Lyrics approved",
            "ok": row["current_macro_state"] in {"LYRICS_APPROVED", "ASSETS_READY", "PREVIEW_PENDING", "VIDEO_APPROVED", "PUBLISHED"},
            "fix": "Approve lyrics",
        },
        {"key": "timestamps", "label": "Timings exist", "ok": files["timestamps"], "fix": "Run or approve sync"},
        {
            "key": "timingWarnings",
            "label": "No critical timing errors",
            "ok": len(critical_sync_warnings) == 0,
            "fix": "Fix overlap or duration warnings in Sync",
        },
        {"key": "design", "label": "Template selected", "ok": files["design"], "fix": "Save a design template"},
        {"key": "disk", "label": "Enough disk space", "ok": free_bytes > 1_000_000_000, "fix": "Free at least 1 GB"},
    ]
    return {
        "projectId": project_id,
        "ready": all(item["ok"] for item in checks),
        "checks": checks,
        "freeDiskBytes": free_bytes,
        "warnings": critical_sync_warnings,
        "renderOptions": _default_render_options(get_project_design(project_id)),
    }


def list_jobs(project_id: str | None = None, limit: int = 80) -> list[dict[str, Any]]:
    init_web_studio()
    with _connect() as conn:
        if project_id:
            rows = conn.execute(
                "SELECT * FROM jobs WHERE project_id=? ORDER BY created_at DESC, id DESC LIMIT ?",
                (project_id, limit),
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM jobs ORDER BY created_at DESC, id DESC LIMIT ?", (limit,)).fetchall()
    return [_job_from_row(row) for row in rows]


def get_job(job_id: int) -> dict[str, Any]:
    init_web_studio()
    with _connect() as conn:
        row = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    if row is None:
        raise KeyError(str(job_id))
    return _job_from_row(row)


def start_project_job(project_id: str, job_type: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    init_web_studio()
    payload = payload or {}
    row = _song_row(project_id)
    if row is None:
        raise KeyError(project_id)
    job_type = _normalize_job_type(job_type)
    workspace = _ensure_workspace(project_id, row["workspace_dir"])
    message = _request_pipeline_state(project_id, row, job_type, payload)
    job_id = _insert_job(project_id, job_type, "queued", 0, message, log_path=str(workspace / "logs"))
    _start_job_thread(job_id, project_id, job_type, payload)
    _record_event(project_id, "job_queued", message)
    return get_job(job_id)


def cancel_job(job_id: int) -> dict[str, Any]:
    init_web_studio()
    job = get_job(job_id)
    with _connect() as conn:
        conn.execute(
            """
            UPDATE jobs
            SET cancel_requested=1, status='cancel_requested', message='Cancel requested'
            WHERE id=?
            """,
            (job_id,),
        )
        conn.commit()
    if job.get("projectId"):
        db_manager.request_abort(str(job["projectId"]))
        _record_event(str(job["projectId"]), "job_cancel_requested", f"Cancel requested for {job['jobType']}")
    return get_job(job_id)


def project_media_path(project_id: str, kind: str) -> Path:
    init_web_studio()
    row = _song_row(project_id)
    if row is None:
        raise KeyError(project_id)
    workspace = _workspace_path(project_id, row["workspace_dir"])
    normalized = kind.strip().lower()
    candidates: list[Path] = []

    if normalized == "audio":
        candidates = [workspace / "audio.mp3", workspace / "source" / "audio.mp3"]
    elif normalized == "preview":
        preview_dir = workspace / "renders" / "previews"
        candidates = [workspace / "final_video_preview.mp4", workspace / "preview.mp4"]
        if preview_dir.exists():
            candidates.extend(sorted(preview_dir.glob("*.mp4"), key=lambda item: item.stat().st_mtime, reverse=True))
    elif normalized == "final":
        candidates = [workspace / "final_video.mp4", workspace / "renders" / "final" / "final_video.mp4"]
    else:
        raise ValueError(f"Unknown media kind: {kind}")

    workspace_root = workspace.resolve()
    for candidate in candidates:
        if not candidate.exists() or not candidate.is_file():
            continue
        resolved = candidate.resolve()
        if str(resolved).startswith(str(workspace_root)):
            return resolved
    raise FileNotFoundError(kind)


def get_upload_metadata(project_id: str) -> dict[str, Any]:
    init_web_studio()
    row = _song_row(project_id)
    if row is None:
        raise KeyError(project_id)
    workspace = _workspace_path(project_id, row["workspace_dir"])
    metadata = _read_json_file(_upload_metadata_path(workspace)) or _default_upload_metadata(row)
    metadata.setdefault("projectId", project_id)
    metadata.setdefault("metadataPath", str(_upload_metadata_path(workspace)))
    metadata.setdefault("publishedUrl", _published_url(workspace))
    return metadata


def generate_upload_metadata(project_id: str) -> dict[str, Any]:
    init_web_studio()
    row = _song_row(project_id)
    if row is None:
        raise KeyError(project_id)
    metadata = _default_upload_metadata(row)
    metadata["description"] = (
        f"Lyric video for {row['title'] or 'Untitled Project'} by {row['artist'] or 'Unknown Artist'}.\n\n"
        "Created locally with EchoForge Web Studio."
    )
    metadata["tags"] = _metadata_tags(row)
    return save_upload_metadata(project_id, metadata)


def save_upload_metadata(project_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    init_web_studio()
    row = _song_row(project_id)
    if row is None:
        raise KeyError(project_id)
    workspace = _workspace_path(project_id, row["workspace_dir"])
    metadata = _normalize_upload_metadata(payload, row)
    _atomic_write_text(_upload_metadata_path(workspace), json.dumps(metadata, indent=2, ensure_ascii=False) + "\n")
    _atomic_write_text(workspace / "description.txt", metadata["description"].strip() + "\n")
    _record_event(project_id, "upload_metadata_saved", "Upload metadata saved")
    return get_upload_metadata(project_id)


def approve_upload(project_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    init_web_studio()
    metadata = save_upload_metadata(project_id, payload or get_upload_metadata(project_id))
    job = start_project_job(project_id, "upload_youtube", metadata)
    return {"metadata": get_upload_metadata(project_id), "job": job, "project": get_project(project_id)}


def get_app_settings() -> dict[str, Any]:
    init_web_studio()
    raw = db_manager.get_setting("web_studio_settings")
    settings = DEFAULT_APP_SETTINGS.copy()
    if raw:
        try:
            settings.update(json.loads(raw))
        except json.JSONDecodeError:
            pass
    settings["workspaceRoot"] = str(WORKSPACES_DIR)
    settings["databasePath"] = str(db_manager.DB_PATH)
    settings["remotionPath"] = str(ROOT_DIR / "renderer" / "remotion")
    return settings


def save_app_settings(payload: dict[str, Any]) -> dict[str, Any]:
    init_web_studio()
    settings = get_app_settings()
    allowed = {
        "theme",
        "defaultCountry",
        "defaultPrivacy",
        "autosaveSeconds",
        "renderQuality",
        "previewResolution",
    }
    for key in allowed:
        if key in payload:
            settings[key] = payload[key]
    db_manager.set_setting("web_studio_settings", json.dumps(settings, ensure_ascii=False))
    _record_event(None, "settings_saved", "Studio settings saved")
    return get_app_settings()


def list_project_files(project_id: str) -> list[dict[str, Any]]:
    row = _song_row(project_id)
    if row is None:
        raise KeyError(project_id)
    workspace = _workspace_path(project_id, row["workspace_dir"])
    if not workspace.exists():
        return []
    files: list[dict[str, Any]] = []
    for path in sorted(workspace.rglob("*")):
        if path.is_file():
            stat = path.stat()
            files.append(
                {
                    "name": path.name,
                    "relativePath": str(path.relative_to(workspace)),
                    "size": stat.st_size,
                    "updatedAt": datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
                    "kind": _file_kind(path),
                }
            )
    return files


def read_logs(project_id: str | None = None, limit: int = 80) -> list[dict[str, Any]]:
    init_web_studio()
    items: list[dict[str, Any]] = []
    with _connect() as conn:
        if project_id:
            rows = conn.execute(
                "SELECT * FROM logs WHERE project_id=? ORDER BY created_at DESC LIMIT ?",
                (project_id, limit),
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM logs ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
    for row in rows:
        items.append(
            {
                "time": row["created_at"],
                "level": "info",
                "projectId": row["project_id"],
                "message": row["message"],
                "eventType": row["event_type"],
            }
        )

    if len(items) < limit and LOG_FILE.exists():
        needed = limit - len(items)
        lines = _tail_lines(LOG_FILE, needed)
        for line in reversed(lines):
            if project_id and project_id not in line:
                continue
            items.append({"time": "", "level": _log_level(line), "projectId": project_id, "message": line})
    return items[:limit]


def _project_from_row(row: sqlite3.Row) -> dict[str, Any]:
    raw_state = row["current_macro_state"] or "DISCOVERED"
    meta = get_state_meta(raw_state)
    workspace = _workspace_path(row["video_id"], row["workspace_dir"])
    files = _workspace_flags(workspace)
    progress = max(meta.progress, _progress_from_files(files))
    checklist = _checklist(files, raw_state)
    project = {
        "id": row["video_id"],
        "videoId": row["video_id"],
        "title": row["title"] or "Untitled Project",
        "artist": row["artist"] or "Unknown Artist",
        "sourceUrl": row["url"] or f"https://www.youtube.com/watch?v={row['video_id']}",
        "rawState": raw_state,
        "studioState": meta.studio_state,
        "statusLabel": meta.label,
        "statusTone": meta.tone,
        "microState": row["current_micro_state"] or "IDLE",
        "targetState": row["target_macro_state"] or "STAGED",
        "workspacePath": str(workspace),
        "updatedAt": row["updated_at"],
        "progress": min(progress, 100),
        "nextAction": meta.next_action,
        "primaryAction": action_key_for_state(raw_state, row["target_macro_state"]),
        "checklist": checklist,
        "filesReady": files,
    }
    return project


def _song_row(project_id: str) -> sqlite3.Row | None:
    with _connect() as conn:
        return conn.execute("SELECT * FROM songs WHERE video_id=?", (project_id,)).fetchone()


def _workspace_path(project_id: str, workspace_dir: str | None) -> Path:
    if workspace_dir:
        return Path(workspace_dir)
    return WORKSPACES_DIR / project_id


def _ensure_workspace(project_id: str, workspace_dir: str | None = None) -> Path:
    path = _workspace_path(project_id, workspace_dir)
    path.mkdir(parents=True, exist_ok=True)
    db_manager.update_state(project_id, workspace_dir=str(path))
    return path


def _workspace_flags(workspace: Path) -> dict[str, bool]:
    def any_exists(*relative: str) -> bool:
        return any((workspace / item).exists() for item in relative)

    return {
        "audio": any_exists("audio.mp3", "source/audio.mp3"),
        "lyrics": any_exists("lyrics.lrc", "lyrics.txt", "lyrics/lyrics.lrc", "lyrics/lyrics.txt"),
        "timestamps": any_exists("timestamps.json", "sync/timestamps.json"),
        "draftTimestamps": any_exists("timestamps.draft.json", "sync/timestamps.draft.json"),
        "preview": any_exists("final_video_preview.mp4", "preview.mp4", "renders/previews/preview_001.mp4"),
        "final": any_exists("final_video.mp4", "renders/final/final_video.mp4"),
        "published": any_exists("published_url.txt", "upload/published_url.txt"),
        "design": any_exists("template.json", "design/template.json", "render_props.json", "design/render_props.json"),
    }


def _progress_from_files(files: dict[str, bool]) -> int:
    progress = 0
    weights = {
        "audio": 18,
        "lyrics": 18,
        "timestamps": 22,
        "design": 8,
        "preview": 12,
        "final": 14,
        "published": 8,
    }
    for key, weight in weights.items():
        if files.get(key):
            progress += weight
    return progress


def _checklist(files: dict[str, bool], raw_state: str) -> list[dict[str, Any]]:
    done = {
        "audio": files["audio"],
        "lyrics": files["lyrics"],
        "lyricsApproved": raw_state
        in {"LYRICS_APPROVED", "ASSETS_READY", "PREVIEW_PENDING", "VIDEO_APPROVED", "PUBLISHED"},
        "timestamps": files["timestamps"],
        "syncApproved": raw_state in {"ASSETS_READY", "PREVIEW_PENDING", "VIDEO_APPROVED", "PUBLISHED"},
        "design": files["design"] or raw_state in {"ASSETS_READY", "PREVIEW_PENDING", "VIDEO_APPROVED", "PUBLISHED"},
        "preview": files["preview"] or raw_state in {"PREVIEW_PENDING", "VIDEO_APPROVED", "PUBLISHED"},
        "final": files["final"],
        "uploaded": files["published"] or raw_state == "PUBLISHED",
    }
    return [{"key": key, "label": label, "done": bool(done.get(key))} for key, label in CHECKLIST]


def _resume_if_paused_or_discovered(project_id: str, song: dict[str, Any]) -> None:
    raw_state = song.get("current_macro_state")
    if raw_state == "DISCOVERED":
        db_manager.update_state(project_id, macro="STAGED", micro="IDLE", workspace_dir=str(_ensure_workspace(project_id)))
    elif raw_state == "PAUSED":
        db_manager.update_state(project_id, macro=_retry_macro_from_workspace(song), micro="IDLE")


def _retry_macro_from_workspace(song: dict[str, Any]) -> str:
    workspace = song.get("workspace_dir")
    if not workspace:
        return "STAGED"
    root = Path(workspace)
    if (root / "final_video.mp4").exists() or (root / "renders" / "final" / "final_video.mp4").exists():
        return "VIDEO_APPROVED"
    if (root / "timestamps.json").exists() or (root / "sync" / "timestamps.json").exists():
        return "ASSETS_READY"
    if any((root / name).exists() for name in ("lyrics.lrc", "lyrics.txt", "lyrics/lyrics.lrc", "lyrics/lyrics.txt")):
        return "LYRICS_APPROVED"
    if (root / "audio.mp3").exists() or (root / "source" / "audio.mp3").exists():
        return "AUDIO_FETCHED"
    return "STAGED"


def _backup_lyrics_if_present(project_id: str, song: dict[str, Any]) -> None:
    workspace = _workspace_path(project_id, song.get("workspace_dir"))
    for name in ("lyrics.lrc", "lyrics.txt", "lyrics/lyrics.lrc", "lyrics/lyrics.txt"):
        path = workspace / name
        if path.exists():
            _backup_file_version(project_id, path, approved=True, notes="Approved from Web Studio shell")
            return


def _lyrics_draft_path(workspace: Path) -> Path:
    return workspace / "lyrics.draft.txt"


def _lyrics_active_path(workspace: Path) -> Path:
    for name in ("lyrics.lrc", "lyrics.txt", "lyrics/lyrics.lrc", "lyrics/lyrics.txt"):
        path = workspace / name
        if path.exists():
            return path
    return workspace / "lyrics.txt"


def _lyrics_target_path(workspace: Path, lines: list[dict[str, Any]]) -> Path:
    active = _lyrics_active_path(workspace)
    if active.exists():
        return active
    return workspace / ("lyrics.lrc" if _content_has_timestamps(lines) else "lyrics.txt")


def _parse_lyric_lines(content: str) -> list[dict[str, Any]]:
    parsed: list[dict[str, Any]] = []
    lrc_pattern = re.compile(r"^\[(\d{1,2}):(\d{2})(?:\.(\d{1,3}))?\](.*)$")
    for index, raw_line in enumerate(content.splitlines(), 1):
        raw = raw_line.rstrip("\n")
        timestamp = None
        text = raw
        match = lrc_pattern.match(raw.strip())
        if match:
            minute, second, fraction, text = match.groups()
            fraction = (fraction or "000").ljust(3, "0")[:3]
            timestamp = f"{int(minute):02d}:{int(second):02d}.{fraction}"
            text = text.strip()
        line_type = _lyric_line_type(text)
        parsed.append(
            {
                "id": f"line_{index:04d}",
                "index": index,
                "type": line_type,
                "text": text,
                "timestamp": timestamp,
                "raw": raw,
            }
        )
    if not parsed:
        parsed.append({"id": "line_0001", "index": 1, "type": "lyric", "text": "", "timestamp": None, "raw": ""})
    return parsed


def _lyrics_lines_from_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    if isinstance(payload.get("lines"), list):
        lines = []
        for index, line in enumerate(payload["lines"], 1):
            text = str(line.get("text") or "")
            timestamp = line.get("timestamp") or None
            line_type = str(line.get("type") or _lyric_line_type(text))
            lines.append(
                {
                    "id": str(line.get("id") or f"line_{index:04d}"),
                    "index": index,
                    "type": line_type,
                    "text": text,
                    "timestamp": str(timestamp) if timestamp else None,
                    "raw": str(line.get("raw") or text),
                }
            )
        return lines
    return _parse_lyric_lines(str(payload.get("text") or ""))


def _render_lyrics_lines(lines: list[dict[str, Any]]) -> str:
    rendered = []
    has_timestamps = _content_has_timestamps(lines)
    for line in lines:
        text = str(line.get("text") or "").strip()
        timestamp = line.get("timestamp")
        if has_timestamps and timestamp:
            rendered.append(f"[{timestamp}]{text}")
        else:
            rendered.append(text)
    return "\n".join(rendered).rstrip() + "\n"


def _content_has_timestamps(lines: list[dict[str, Any]]) -> bool:
    return any(bool(line.get("timestamp")) for line in lines)


def _lyric_line_type(text: str) -> str:
    cleaned = text.strip()
    if not cleaned:
        return "note"
    if re.match(r"^\[[^\]]+\]$", cleaned):
        return "section_label"
    if "instrumental" in cleaned.lower():
        return "instrumental"
    return "lyric"


def _lyrics_warnings(lines: list[dict[str, Any]]) -> list[dict[str, Any]]:
    warnings: list[dict[str, Any]] = []
    seen: dict[str, list[int]] = {}
    for line in lines:
        text = str(line.get("text") or "").strip()
        line_id = line.get("id")
        index = line.get("index")
        line_type = line.get("type")
        if line_type == "lyric" and not text:
            warnings.append({"lineId": line_id, "index": index, "severity": "warning", "message": "Empty lyric line"})
        if line_type == "lyric" and len(text) > 90:
            warnings.append({"lineId": line_id, "index": index, "severity": "warning", "message": "Very long lyric line"})
        if line_type == "lyric" and 0 < len(text) < 3:
            warnings.append({"lineId": line_id, "index": index, "severity": "info", "message": "Very short lyric line"})
        if line_type == "section_label":
            warnings.append({"lineId": line_id, "index": index, "severity": "info", "message": "Section label"})
        normalized = re.sub(r"\s+", " ", text.lower())
        if line_type == "lyric" and normalized:
            seen.setdefault(normalized, []).append(int(index))

    for indexes in seen.values():
        if len(indexes) > 1:
            for index in indexes:
                line = lines[index - 1]
                warnings.append(
                    {
                        "lineId": line.get("id"),
                        "index": index,
                        "severity": "info",
                        "message": "Repeated lyric line",
                    }
                )
    return warnings


def _timestamps_active_path(workspace: Path) -> Path:
    for name in ("timestamps.json", "sync/timestamps.json"):
        path = workspace / name
        if path.exists():
            return path
    return workspace / "timestamps.json"


def _timestamps_draft_path(workspace: Path) -> Path:
    for name in ("timestamps.draft.json", "sync/timestamps.draft.json"):
        path = workspace / name
        if path.exists():
            return path
    active_path = _timestamps_active_path(workspace)
    if active_path.parent.name == "sync":
        return active_path.parent / "timestamps.draft.json"
    return workspace / "timestamps.draft.json"


def _timestamp_segments_from_json(content: str) -> list[dict[str, Any]]:
    try:
        data = json.loads(content)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid timestamps JSON: {exc.msg}") from exc

    if isinstance(data, list):
        raw_segments = data
    elif isinstance(data, dict):
        raw_segments = data.get("segments") or data.get("lines") or []
    else:
        raw_segments = []
    if not isinstance(raw_segments, list):
        raw_segments = []
    return [_normalize_timestamp_segment(segment, index) for index, segment in enumerate(raw_segments, 1)]


def _timestamp_segments_from_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    if isinstance(payload.get("segments"), list):
        raw_segments = payload["segments"]
    elif payload.get("text") is not None:
        return _timestamp_segments_from_json(str(payload.get("text") or ""))
    else:
        raw_segments = []
    return [_normalize_timestamp_segment(segment, index) for index, segment in enumerate(raw_segments, 1)]


def _normalize_timestamp_segment(raw_segment: Any, index: int) -> dict[str, Any]:
    segment = raw_segment if isinstance(raw_segment, dict) else {}
    start = _coerce_seconds(segment.get("start") or segment.get("timestamp"), 0.0)
    end = _coerce_seconds(segment.get("end"), start + 3.0)
    if end < start:
        end = start
    text = str(segment.get("text") or segment.get("line") or "").strip()
    words = segment.get("words") if isinstance(segment.get("words"), list) else []
    normalized_words = []
    for word in words:
        if not isinstance(word, dict):
            continue
        word_text = str(word.get("word") or word.get("text") or "").strip()
        if not word_text:
            continue
        normalized_words.append(
            {
                "word": word_text,
                "start": round(_coerce_seconds(word.get("start"), start), 3),
                "end": round(_coerce_seconds(word.get("end"), end), 3),
            }
        )
    return {
        "id": str(segment.get("id") or f"seg_{index:04d}"),
        "index": index,
        "start": round(max(0.0, start), 3),
        "end": round(max(0.0, end), 3),
        "text": text,
        "words": normalized_words,
    }


def _render_timestamp_segments(segments: list[dict[str, Any]]) -> str:
    clean_segments = []
    for index, segment in enumerate(segments, 1):
        clean_segments.append(
            {
                "text": str(segment.get("text") or "").strip(),
                "start": round(_coerce_seconds(segment.get("start"), 0.0), 3),
                "end": round(_coerce_seconds(segment.get("end"), 0.0), 3),
                "words": segment.get("words") if isinstance(segment.get("words"), list) else [],
            }
        )
        if clean_segments[-1]["end"] < clean_segments[-1]["start"]:
            clean_segments[-1]["end"] = clean_segments[-1]["start"]
        segments[index - 1]["index"] = index
    return json.dumps({"segments": clean_segments}, indent=2, ensure_ascii=False) + "\n"


def _timestamp_warnings(segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    warnings: list[dict[str, Any]] = []
    if not segments:
        return [
            {
                "segmentId": "",
                "index": 0,
                "severity": "danger",
                "message": "No sync timing rows found",
            }
        ]

    previous_end = 0.0
    for segment in segments:
        segment_id = str(segment.get("id") or "")
        index = int(segment.get("index") or 0)
        start = _coerce_seconds(segment.get("start"), 0.0)
        end = _coerce_seconds(segment.get("end"), 0.0)
        duration = end - start
        text = str(segment.get("text") or "").strip()

        if not text:
            warnings.append(
                {"segmentId": segment_id, "index": index, "severity": "warning", "message": "Empty lyric text"}
            )
        if start < 0:
            warnings.append(
                {"segmentId": segment_id, "index": index, "severity": "danger", "message": "Start time is negative"}
            )
        if duration <= 0:
            warnings.append(
                {"segmentId": segment_id, "index": index, "severity": "danger", "message": "End time must be after start"}
            )
        elif duration < 0.35:
            warnings.append(
                {"segmentId": segment_id, "index": index, "severity": "warning", "message": "Very short display time"}
            )
        elif duration > 12:
            warnings.append(
                {"segmentId": segment_id, "index": index, "severity": "warning", "message": "Very long display time"}
            )
        if index > 1 and start < previous_end - 0.01:
            warnings.append(
                {"segmentId": segment_id, "index": index, "severity": "danger", "message": "Timing overlaps previous row"}
            )
        elif index > 1 and start - previous_end > 8:
            warnings.append(
                {"segmentId": segment_id, "index": index, "severity": "info", "message": "Large gap before this row"}
            )
        previous_end = max(previous_end, end)
    return warnings


def _timestamp_duration(segments: list[dict[str, Any]]) -> float:
    if not segments:
        return 0.0
    return round(max(_coerce_seconds(segment.get("end"), 0.0) for segment in segments), 3)


def _coerce_seconds(value: Any, default: float = 0.0) -> float:
    if value is None or value == "":
        return default
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text:
        return default
    if ":" in text:
        parts = text.split(":")
        try:
            seconds = float(parts[-1])
            minutes = int(parts[-2]) if len(parts) >= 2 else 0
            hours = int(parts[-3]) if len(parts) >= 3 else 0
            return hours * 3600 + minutes * 60 + seconds
        except ValueError:
            return default
    try:
        return float(text)
    except ValueError:
        return default


def _backup_file_version(project_id: str, path: Path, approved: bool, notes: str) -> Path | None:
    if not path.exists():
        return None
    workspace = _workspace_path(project_id, None)
    row = _song_row(project_id)
    if row is not None:
        workspace = _workspace_path(project_id, row["workspace_dir"])
    version_dir = workspace / "lyrics" / "versions"
    version_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    version_path = version_dir / f"{path.stem}_{stamp}{path.suffix}"
    version_path.write_text(path.read_text(encoding="utf-8", errors="replace"), encoding="utf-8")
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO lyrics_versions
                (project_id, file_path, version_label, notes, is_approved)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                project_id,
                str(version_path),
                ("approved" if approved else "backup") + f"-{stamp}",
                notes,
                1 if approved else 0,
            ),
        )
        conn.commit()
    return version_path


def _backup_timestamp_version(project_id: str, path: Path, approved: bool, notes: str) -> Path | None:
    if not path.exists():
        return None
    workspace = _workspace_path(project_id, None)
    row = _song_row(project_id)
    if row is not None:
        workspace = _workspace_path(project_id, row["workspace_dir"])
    version_dir = workspace / "sync" / "versions"
    version_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    version_path = version_dir / f"{path.stem}_{stamp}{path.suffix}"
    version_path.write_text(path.read_text(encoding="utf-8", errors="replace"), encoding="utf-8")
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO timestamp_versions
                (project_id, file_path, version_label, notes, is_approved)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                project_id,
                str(version_path),
                ("approved" if approved else "backup") + f"-{stamp}",
                notes,
                1 if approved else 0,
            ),
        )
        conn.commit()
    return version_path


def _seed_default_templates(conn: sqlite3.Connection) -> None:
    count = conn.execute("SELECT COUNT(*) FROM templates").fetchone()[0]
    if count:
        return
    for template in DEFAULT_TEMPLATES:
        conn.execute(
            """
            INSERT INTO templates
                (name, aspect_ratio, settings_json, is_default)
            VALUES (?, ?, ?, ?)
            """,
            (
                template["name"],
                template["aspectRatio"],
                json.dumps(
                    {
                        "description": template["description"],
                        "settings": template["settings"],
                    },
                    ensure_ascii=False,
                ),
                1 if template["isDefault"] else 0,
            ),
        )


def _template_from_row(row: sqlite3.Row) -> dict[str, Any]:
    payload = _json_loads(row["settings_json"], {})
    return {
        "id": row["id"],
        "name": row["name"],
        "description": payload.get("description", ""),
        "aspectRatio": row["aspect_ratio"],
        "settings": payload.get("settings", {}),
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
        "isDefault": bool(row["is_default"]),
    }


def _template_by_id(template_id: Any) -> dict[str, Any] | None:
    try:
        normalized_id = int(template_id)
    except (TypeError, ValueError):
        return None
    with _connect() as conn:
        row = conn.execute(
            """
            SELECT id, name, aspect_ratio, settings_json, created_at, updated_at, is_default
            FROM templates
            WHERE id=?
            """,
            (normalized_id,),
        ).fetchone()
    return _template_from_row(row) if row else None


def _design_path(workspace: Path) -> Path:
    return workspace / "design" / "template.json"


def _render_props_path(workspace: Path) -> Path:
    return workspace / "design" / "render_props.json"


def _upload_metadata_path(workspace: Path) -> Path:
    return workspace / "upload" / "metadata.json"


def _read_json_file(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def _json_loads(value: str | None, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


def _normalized_design_settings(settings: dict[str, Any]) -> dict[str, Any]:
    defaults = DEFAULT_TEMPLATES[0]["settings"].copy()
    defaults.update(settings)
    defaults["fps"] = int(defaults.get("fps") or 30)
    defaults["fontSize"] = int(defaults.get("fontSize") or 64)
    defaults["watermark"] = bool(defaults.get("watermark", True))
    return defaults


def _default_render_options(design: dict[str, Any]) -> dict[str, Any]:
    settings = design.get("settings") if isinstance(design.get("settings"), dict) else {}
    return {
        "resolution": settings.get("resolution", "1080p"),
        "fps": int(settings.get("fps") or 30),
        "quality": get_app_settings().get("renderQuality", "standard"),
        "format": "mp4",
        "aspectRatio": settings.get("aspectRatio", "16:9"),
    }


def _normalize_job_type(job_type: str) -> str:
    normalized = job_type.replace("-", "_").strip().lower()
    aliases = {
        "download": "download_audio",
        "lyrics": "fetch_lyrics",
        "sync": "auto_sync",
        "render": "render_final",
        "render_preview": "render_preview",
        "render_final": "render_final",
        "upload": "upload_youtube",
    }
    normalized = aliases.get(normalized, normalized)
    allowed = {
        "download_audio",
        "fetch_lyrics",
        "auto_sync",
        "render_preview",
        "render_final",
        "upload_youtube",
    }
    if normalized not in allowed:
        raise ValueError(f"Unknown job type: {job_type}")
    return normalized


def _request_pipeline_state(project_id: str, row: sqlite3.Row, job_type: str, payload: dict[str, Any]) -> str:
    raw_state = row["current_macro_state"] or "DISCOVERED"
    workspace = _workspace_path(project_id, row["workspace_dir"])
    files = _workspace_flags(workspace)

    if job_type == "download_audio":
        if raw_state in {"DISCOVERED", "PAUSED", "FAILED"}:
            db_manager.update_state(
                project_id,
                macro="STAGED",
                micro="IDLE",
                workspace_dir=str(_ensure_workspace(project_id, row["workspace_dir"])),
            )
        db_manager.set_target_state(project_id, "AUDIO_FETCHED")
        return "Audio download requested"

    if job_type == "fetch_lyrics":
        if not files["audio"] and raw_state != "AUDIO_FETCHED":
            raise ValueError("Audio is required before lyrics can be fetched")
        db_manager.update_state(project_id, macro="AUDIO_FETCHED", micro="IDLE")
        db_manager.set_target_state(project_id, "LYRICS_REVIEW_PENDING")
        return "Lyrics fetch requested"

    if job_type == "auto_sync":
        if not files["lyrics"]:
            raise ValueError("Lyrics are required before auto-sync")
        if raw_state == "LYRICS_REVIEW_PENDING":
            db_manager.update_state(project_id, macro="LYRICS_APPROVED", micro="IDLE")
        elif raw_state not in {"LYRICS_APPROVED", "ASSETS_READY", "FAILED", "PAUSED"}:
            raise ValueError("Approve lyrics before auto-sync")
        if raw_state in {"FAILED", "PAUSED"}:
            db_manager.update_state(project_id, macro="LYRICS_APPROVED", micro="IDLE")
        db_manager.set_target_state(project_id, "ASSETS_READY")
        return "Auto-sync requested"

    if job_type in {"render_preview", "render_final"}:
        readiness = render_readiness(project_id)
        if not readiness["ready"]:
            missing = ", ".join(item["label"] for item in readiness["checks"] if not item["ok"])
            raise ValueError(f"Render blocked: {missing}")
        db_manager.update_state(project_id, macro="ASSETS_READY", micro="IDLE")
        db_manager.set_target_state(project_id, "PREVIEW_PENDING")
        return "Render requested"

    if job_type == "upload_youtube":
        if payload:
            save_upload_metadata(project_id, payload)
        files = _workspace_flags(workspace)
        if not files["final"]:
            raise ValueError("Final video is required before upload")
        db_manager.update_state(project_id, macro="VIDEO_APPROVED", micro="IDLE")
        db_manager.set_target_state(project_id, "PUBLISHED")
        return "YouTube upload requested"

    raise ValueError(f"Unknown job type: {job_type}")


def _insert_job(project_id: str, job_type: str, status: str, progress: int, message: str, log_path: str = "") -> int:
    with _connect() as conn:
        cursor = conn.execute(
            """
            INSERT INTO jobs
                (project_id, job_type, status, progress, message, log_path)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (project_id, job_type, status, progress, message, log_path),
        )
        conn.commit()
        return int(cursor.lastrowid)


def _start_job_thread(job_id: int, project_id: str, job_type: str, payload: dict[str, Any]) -> None:
    thread = threading.Thread(
        target=_run_job_worker,
        args=(job_id, project_id, job_type, payload),
        name=f"echoforge-job-{job_id}",
        daemon=True,
    )
    with _JOB_LOCK:
        _JOB_THREADS[job_id] = thread
    thread.start()


def _run_job_worker(job_id: int, project_id: str, job_type: str, payload: dict[str, Any]) -> None:
    try:
        if _job_cancel_requested(job_id):
            _finish_cancelled_job(job_id, project_id)
            return

        row = _song_row(project_id)
        if row is None:
            raise KeyError(project_id)
        workspace = _ensure_workspace(project_id, row["workspace_dir"])
        song = dict(row)
        song["workspace_dir"] = str(workspace)

        _set_job_fields(job_id, status="running", progress=8, message=_job_running_message(job_type), started_at="now")
        ok, final_state, message = _execute_project_job(job_id, project_id, job_type, song, payload)

        if _job_cancel_requested(job_id):
            _finish_cancelled_job(job_id, project_id)
            return

        if ok:
            db_manager.update_state(project_id, macro=final_state, micro="IDLE")
            _set_job_fields(job_id, status="completed", progress=100, message=message, finished_at="now")
            _record_event(project_id, "job_completed", message)
        else:
            db_manager.update_state(project_id, macro="FAILED", micro="IDLE")
            _set_job_fields(
                job_id,
                status="failed",
                progress=100,
                message="Job failed",
                error_message=message,
                finished_at="now",
            )
            _record_event(project_id, "job_failed", message)
    except Exception as exc:
        db_manager.update_state(project_id, macro="FAILED", micro="IDLE")
        _set_job_fields(
            job_id,
            status="failed",
            progress=100,
            message="Job failed",
            error_message=str(exc),
            finished_at="now",
        )
        _record_event(project_id, "job_failed", str(exc))
    finally:
        with _JOB_LOCK:
            _JOB_THREADS.pop(job_id, None)


def _execute_project_job(
    job_id: int,
    project_id: str,
    job_type: str,
    song: dict[str, Any],
    payload: dict[str, Any],
) -> tuple[bool, str, str]:
    from echoforge.engine.workers import ai_sync, fetch_audio, fetch_lyrics, render_video, youtube_upload

    if job_type == "download_audio":
        db_manager.update_state(project_id, macro="STAGED", micro="DOWNLOADING_AUDIO")
        _set_job_fields(job_id, progress=20, message="Downloading audio")
        ok = fetch_audio.download(song)
        return ok, "AUDIO_FETCHED", "Audio downloaded" if ok else "Audio download failed"

    if job_type == "fetch_lyrics":
        db_manager.update_state(project_id, macro="AUDIO_FETCHED", micro="FETCHING_LYRICS")
        _set_job_fields(job_id, progress=25, message="Fetching lyrics")
        ok = fetch_lyrics.fetch(song)
        return ok, "LYRICS_REVIEW_PENDING", "Lyrics fetched" if ok else "Lyrics fetch failed"

    if job_type == "auto_sync":
        db_manager.update_state(project_id, macro="LYRICS_APPROVED", micro="RUNNING_AI_SYNC")
        _set_job_fields(job_id, progress=25, message="Generating sync timings")
        ok = ai_sync.process(song)
        return ok, "ASSETS_READY", "Sync timings generated" if ok else "Sync generation failed"

    if job_type == "render_preview":
        db_manager.update_state(project_id, macro="ASSETS_READY", micro="RENDERING_PREVIEW")
        _set_job_fields(job_id, progress=25, message="Rendering preview")
        ok = render_video.render(song, mode="preview", preview_duration=float(payload.get("previewDuration") or 45))
        return ok, "PREVIEW_PENDING", "Preview rendered" if ok else "Preview render failed"

    if job_type == "render_final":
        db_manager.update_state(project_id, macro="ASSETS_READY", micro="RENDERING_FINAL")
        _set_job_fields(job_id, progress=25, message="Rendering final video")
        ok = render_video.render(song, mode="final")
        return ok, "VIDEO_APPROVED", "Final video rendered" if ok else "Final render failed"

    if job_type == "upload_youtube":
        if payload:
            save_upload_metadata(project_id, payload)
        db_manager.update_state(project_id, macro="VIDEO_APPROVED", micro="UPLOADING")
        _set_job_fields(job_id, progress=25, message="Uploading to YouTube")
        ok = youtube_upload.upload(song)
        if ok:
            _record_upload_success(project_id, song)
        return ok, "PUBLISHED", "Video uploaded" if ok else "YouTube upload failed"

    raise ValueError(f"Unknown job type: {job_type}")


def _record_upload_success(project_id: str, song: dict[str, Any]) -> None:
    workspace = Path(str(song.get("workspace_dir") or ""))
    metadata = _read_json_file(_upload_metadata_path(workspace)) or {}
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO upload_records (project_id, youtube_url, privacy, metadata_json)
            VALUES (?, ?, ?, ?)
            """,
            (
                project_id,
                _published_url(workspace),
                str(metadata.get("privacy") or "private"),
                json.dumps(metadata, ensure_ascii=False),
            ),
        )
        conn.commit()


def _set_job_fields(job_id: int, **fields: Any) -> None:
    allowed = {"status", "progress", "message", "started_at", "finished_at", "error_message", "log_path"}
    assignments: list[str] = []
    params: list[Any] = []
    for key, value in fields.items():
        if key not in allowed:
            continue
        if key in {"started_at", "finished_at"} and value == "now":
            assignments.append(f"{key}=CURRENT_TIMESTAMP")
        else:
            assignments.append(f"{key}=?")
            params.append(value)
    if not assignments:
        return
    params.append(job_id)
    with _connect() as conn:
        conn.execute(f"UPDATE jobs SET {', '.join(assignments)} WHERE id=?", tuple(params))
        conn.commit()


def _job_cancel_requested(job_id: int) -> bool:
    with _connect() as conn:
        row = conn.execute("SELECT cancel_requested FROM jobs WHERE id=?", (job_id,)).fetchone()
    return bool(row and row["cancel_requested"])


def _finish_cancelled_job(job_id: int, project_id: str) -> None:
    db_manager.update_state(project_id, micro="IDLE")
    _set_job_fields(job_id, status="cancelled", message="Job cancelled", finished_at="now")
    _record_event(project_id, "job_cancelled", "Job cancelled")


def _job_running_message(job_type: str) -> str:
    labels = {
        "download_audio": "Preparing audio download",
        "fetch_lyrics": "Preparing lyrics fetch",
        "auto_sync": "Preparing sync",
        "render_preview": "Preparing preview render",
        "render_final": "Preparing final render",
        "upload_youtube": "Preparing upload",
    }
    return labels.get(job_type, "Preparing job")


def _job_from_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "projectId": row["project_id"],
        "jobType": row["job_type"],
        "status": row["status"],
        "progress": row["progress"],
        "message": row["message"],
        "startedAt": row["started_at"],
        "finishedAt": row["finished_at"],
        "errorMessage": row["error_message"],
        "logPath": row["log_path"],
        "cancelRequested": bool(row["cancel_requested"]),
        "createdAt": row["created_at"],
    }


def _default_upload_metadata(row: sqlite3.Row) -> dict[str, Any]:
    title = row["title"] or "Untitled Project"
    artist = row["artist"] or "Unknown Artist"
    upload_title = f"{title} - {artist} (Lyric Video)"
    return {
        "title": upload_title[:100],
        "description": f"Lyric video for {title} by {artist}.\n\nCreated with EchoForge Web Studio.",
        "tags": _metadata_tags(row),
        "privacy": get_app_settings().get("defaultPrivacy", "private"),
        "madeForKids": False,
        "playlist": "",
        "thumbnailPath": "",
        "scheduleTime": "",
    }


def _metadata_tags(row: sqlite3.Row) -> list[str]:
    title = str(row["title"] or "").strip()
    artist = str(row["artist"] or "").strip()
    tags = ["lyrics", "lyric video", "music"]
    for value in (artist, title):
        if value:
            tags.append(value)
    return tags


def _normalize_upload_metadata(payload: dict[str, Any], row: sqlite3.Row) -> dict[str, Any]:
    defaults = _default_upload_metadata(row)
    tags = payload.get("tags", defaults["tags"])
    if isinstance(tags, str):
        tags = [tag.strip() for tag in tags.split(",") if tag.strip()]
    if not isinstance(tags, list):
        tags = defaults["tags"]
    privacy = str(payload.get("privacy") or defaults["privacy"])
    if privacy not in {"private", "unlisted", "public"}:
        privacy = "private"
    return {
        "title": str(payload.get("title") or defaults["title"]).strip()[:100],
        "description": str(payload.get("description") or defaults["description"]).strip(),
        "tags": [str(tag).strip() for tag in tags if str(tag).strip()],
        "privacy": privacy,
        "madeForKids": bool(payload.get("madeForKids", defaults["madeForKids"])),
        "playlist": str(payload.get("playlist") or ""),
        "thumbnailPath": str(payload.get("thumbnailPath") or ""),
        "scheduleTime": str(payload.get("scheduleTime") or ""),
    }


def _published_url(workspace: Path) -> str:
    for name in ("published_url.txt", "upload/published_url.txt"):
        path = workspace / name
        if path.exists():
            return path.read_text(encoding="utf-8", errors="replace").strip()
    return ""


def _atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f"{path.name}.tmp")
    tmp_path.write_text(content, encoding="utf-8")
    os.replace(tmp_path, path)


def _record_event(project_id: str | None, event_type: str, message: str) -> None:
    with _connect() as conn:
        conn.execute(
            "INSERT INTO logs (project_id, event_type, message) VALUES (?, ?, ?)",
            (project_id, event_type, message),
        )
        conn.commit()


def _extract_video_id(url: str) -> str | None:
    if not url:
        return None
    patterns = (
        r"(?:v=)([A-Za-z0-9_-]{6,})",
        r"youtu\.be/([A-Za-z0-9_-]{6,})",
        r"shorts/([A-Za-z0-9_-]{6,})",
    )
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None


def _manual_project_id(title: str, artist: str, source_url: str) -> str:
    basis = f"{title}|{artist}|{source_url}|{datetime.now().isoformat()}"
    digest = hashlib.sha1(basis.encode("utf-8")).hexdigest()[:10]
    return f"manual_{digest}"


def _file_kind(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".mp3", ".wav", ".m4a"}:
        return "audio"
    if suffix in {".mp4", ".mov", ".webm"}:
        return "video"
    if suffix in {".json", ".lrc", ".txt"}:
        return "data"
    if suffix in {".jpg", ".jpeg", ".png", ".webp"}:
        return "image"
    return "file"


def _tail_lines(path: Path, limit: int) -> list[str]:
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            lines = handle.readlines()
        return [line.rstrip() for line in lines[-limit:] if line.strip()]
    except OSError:
        return []


def _log_level(line: str) -> str:
    upper = line.upper()
    if "ERROR" in upper or "FAILED" in upper:
        return "error"
    if "WARNING" in upper or "WARN" in upper:
        return "warning"
    return "info"
