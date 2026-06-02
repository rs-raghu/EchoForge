"""Application service layer for the local EchoForge Web Studio."""

from __future__ import annotations

import hashlib
import json
import os
import re
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
                """
            )
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
