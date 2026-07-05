from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from echoforge.core.paths import SONGSCOUT_DATA_DIR

SONGSCOUT_DB_PATH = SONGSCOUT_DATA_DIR / "songscout.sqlite3"

VALID_STATUSES = {"new", "selected", "assets_ready", "synced", "rendered", "uploaded", "used", "skipped", "failed"}

CREATE_SONGS_SQL = """
CREATE TABLE IF NOT EXISTS songs (
    id TEXT PRIMARY KEY,
    rank INTEGER,
    title TEXT NOT NULL,
    artist TEXT NOT NULL,
    youtube_url TEXT,
    thumbnail_url TEXT,
    status TEXT NOT NULL DEFAULT 'new',
    project_dir TEXT,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    status_updated_at TEXT,
    note TEXT
);
"""

CREATE_METADATA_SQL = """
CREATE TABLE IF NOT EXISTS metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

CREATE_INDEXES_SQL = [
    "CREATE INDEX IF NOT EXISTS idx_songs_status_rank ON songs(status, rank, title, artist);",
    "CREATE INDEX IF NOT EXISTS idx_songs_rank ON songs(rank);",
    "CREATE INDEX IF NOT EXISTS idx_songs_title ON songs(title);",
    "CREATE INDEX IF NOT EXISTS idx_songs_artist ON songs(artist);",
]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect(path: Path = SONGSCOUT_DB_PATH) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def init_database(path: Path = SONGSCOUT_DB_PATH) -> None:
    with connect(path) as conn:
        conn.execute(CREATE_SONGS_SQL)
        conn.execute(CREATE_METADATA_SQL)
        for statement in CREATE_INDEXES_SQL:
            conn.execute(statement)
        if get_metadata("created_at", conn=conn) is None:
            set_metadata("created_at", now_iso(), conn=conn)
        conn.commit()


def row_to_song(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    item = dict(row)
    return {
        "id": item.get("id"),
        "rank": item.get("rank"),
        "title": item.get("title"),
        "artist": item.get("artist"),
        "youtube_url": item.get("youtube_url"),
        "thumbnail_url": item.get("thumbnail_url"),
        "status": item.get("status") or "new",
        "project_dir": item.get("project_dir"),
        "first_seen_at": item.get("first_seen_at"),
        "last_seen_at": item.get("last_seen_at"),
        "status_updated_at": item.get("status_updated_at"),
        "note": item.get("note"),
    }


def get_metadata(key: str, default: str | None = None, conn: sqlite3.Connection | None = None) -> str | None:
    owns_conn = conn is None
    if conn is None:
        conn = connect()
    try:
        row = conn.execute("SELECT value FROM metadata WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default
    finally:
        if owns_conn:
            conn.close()


def set_metadata(key: str, value: Any, conn: sqlite3.Connection | None = None) -> None:
    owns_conn = conn is None
    if conn is None:
        conn = connect()
    try:
        conn.execute(
            """
            INSERT INTO metadata(key, value)
            VALUES(?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (key, str(value)),
        )
        if owns_conn:
            conn.commit()
    finally:
        if owns_conn:
            conn.close()


def get_all_metadata() -> dict[str, str]:
    init_database()
    with connect() as conn:
        rows = conn.execute("SELECT key, value FROM metadata ORDER BY key").fetchall()
    return {row["key"]: row["value"] for row in rows}


def _clean_song_for_db(song: dict[str, Any], seen_at: str) -> dict[str, Any] | None:
    song_id = str(song.get("id") or "").strip()
    title = str(song.get("title") or "").strip()
    artist = str(song.get("artist") or "").strip()

    if not song_id or not title or not artist:
        return None

    rank = song.get("rank")
    try:
        rank = int(rank) if rank is not None and str(rank).strip() else None
    except (TypeError, ValueError):
        rank = None

    return {
        "id": song_id,
        "rank": rank,
        "title": title,
        "artist": artist,
        "youtube_url": str(song.get("youtube_url") or "").strip() or None,
        "thumbnail_url": str(song.get("thumbnail_url") or "").strip() or None,
        "status": song.get("status") or "new",
        "project_dir": song.get("project_dir"),
        "first_seen_at": seen_at,
        "last_seen_at": seen_at,
        "status_updated_at": song.get("status_updated_at"),
        "note": song.get("note"),
    }


def upsert_songs(songs: list[dict[str, Any]]) -> dict[str, int]:
    """
    Insert/update chart songs.

    Important: workflow fields are preserved on update.
    If a song is already used/skipped/failed, a new Friday scrape will not reset it to new.
    """
    init_database()
    seen_at = now_iso()
    inserted = 0
    updated = 0
    skipped_invalid = 0

    with connect() as conn:
        for song in songs:
            values = _clean_song_for_db(song, seen_at)
            if values is None:
                skipped_invalid += 1
                continue

            existing = conn.execute("SELECT id FROM songs WHERE id = ?", (values["id"],)).fetchone()
            if existing:
                conn.execute(
                    """
                    UPDATE songs
                    SET rank = ?,
                        title = ?,
                        artist = ?,
                        youtube_url = COALESCE(NULLIF(?, ''), youtube_url),
                        thumbnail_url = COALESCE(NULLIF(?, ''), thumbnail_url),
                        last_seen_at = ?
                    WHERE id = ?
                    """,
                    (
                        values["rank"],
                        values["title"],
                        values["artist"],
                        values["youtube_url"],
                        values["thumbnail_url"],
                        values["last_seen_at"],
                        values["id"],
                    ),
                )
                updated += 1
            else:
                conn.execute(
                    """
                    INSERT INTO songs(
                        id, rank, title, artist, youtube_url, thumbnail_url,
                        status, project_dir, first_seen_at, last_seen_at,
                        status_updated_at, note
                    )
                    VALUES(
                        :id, :rank, :title, :artist, :youtube_url, :thumbnail_url,
                        :status, :project_dir, :first_seen_at, :last_seen_at,
                        :status_updated_at, :note
                    )
                    """,
                    values,
                )
                inserted += 1

        set_metadata("last_database_update_at", seen_at, conn=conn)
        conn.commit()

    return {
        "inserted": inserted,
        "updated": updated,
        "skipped_invalid": skipped_invalid,
        "total_songs": count_songs(),
    }


def count_songs() -> int:
    init_database()
    with connect() as conn:
        return int(conn.execute("SELECT COUNT(*) AS c FROM songs").fetchone()["c"])


def workflow_counts() -> dict[str, int]:
    init_database()
    with connect() as conn:
        rows = conn.execute(
            "SELECT status, COUNT(*) AS c FROM songs GROUP BY status ORDER BY status"
        ).fetchall()
    counts = {"new": 0, "selected": 0, "assets_ready": 0, "synced": 0, "rendered": 0, "uploaded": 0, "used": 0, "skipped": 0, "failed": 0}
    counts.update({row["status"]: int(row["c"]) for row in rows})
    counts["total"] = sum(counts.values())
    return counts


def has_any_songs() -> bool:
    return count_songs() > 0


def get_song(song_id: str) -> dict[str, Any] | None:
    init_database()
    with connect() as conn:
        row = conn.execute("SELECT * FROM songs WHERE id = ?", (song_id,)).fetchone()
    return row_to_song(row) if row else None


def get_all_songs(limit: int = 20, status: str | None = None) -> list[dict[str, Any]]:
    init_database()
    limit = max(1, min(int(limit), 500))
    with connect() as conn:
        if status:
            rows = conn.execute(
                """
                SELECT * FROM songs
                WHERE status = ?
                ORDER BY COALESCE(rank, 999999), title COLLATE NOCASE, artist COLLATE NOCASE
                LIMIT ?
                """,
                (status, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT * FROM songs
                ORDER BY COALESCE(rank, 999999), title COLLATE NOCASE, artist COLLATE NOCASE
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
    return [row_to_song(row) for row in rows]


def get_next_available_song(include_failed: bool = False) -> dict[str, Any] | None:
    init_database()
    statuses = ["new"]
    if include_failed:
        statuses.append("failed")
    placeholders = ",".join("?" for _ in statuses)
    with connect() as conn:
        row = conn.execute(
            f"""
            SELECT * FROM songs
            WHERE status IN ({placeholders})
            ORDER BY COALESCE(rank, 999999), title COLLATE NOCASE, artist COLLATE NOCASE
            LIMIT 1
            """,
            statuses,
        ).fetchone()
    return row_to_song(row) if row else None


def mark_song_status(
    song_id: str,
    status: str,
    project_dir: str | None = None,
    note: str | None = None,
) -> dict[str, Any] | None:
    if status not in VALID_STATUSES:
        raise ValueError(f"Invalid status: {status}. Expected one of: {sorted(VALID_STATUSES)}")

    init_database()
    updated_at = now_iso()
    with connect() as conn:
        existing = conn.execute("SELECT id FROM songs WHERE id = ?", (song_id,)).fetchone()
        if not existing:
            return None

        conn.execute(
            """
            UPDATE songs
            SET status = ?,
                project_dir = COALESCE(?, project_dir),
                note = COALESCE(?, note),
                status_updated_at = ?
            WHERE id = ?
            """,
            (status, project_dir, note, updated_at, song_id),
        )
        conn.commit()

    return get_song(song_id)


def reset_workflow_status() -> dict[str, int]:
    init_database()
    with connect() as conn:
        conn.execute(
            """
            UPDATE songs
            SET status = 'new',
                project_dir = NULL,
                note = NULL,
                status_updated_at = ?
            """,
            (now_iso(),),
        )
        conn.commit()
    return workflow_counts()


def record_scrape_result(
    *,
    success: bool,
    row_count: int = 0,
    clean_count: int = 0,
    reason: str = "",
) -> None:
    init_database()
    timestamp = now_iso()
    today = datetime.now().astimezone().date().isoformat()
    with connect() as conn:
        set_metadata("last_scrape_attempt_at", timestamp, conn=conn)
        set_metadata("last_scrape_status", "success" if success else "failed", conn=conn)
        set_metadata("last_scrape_row_count", row_count, conn=conn)
        set_metadata("last_scrape_clean_count", clean_count, conn=conn)
        if reason:
            set_metadata("last_scrape_reason", reason, conn=conn)
        if success:
            set_metadata("last_successful_scrape_at", timestamp, conn=conn)
            set_metadata("last_successful_scrape_date", today, conn=conn)
        conn.commit()


def export_database_json(output_path: Path) -> dict[str, Any]:
    init_database()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "metadata": get_all_metadata(),
        "counts": workflow_counts(),
        "songs": get_all_songs(limit=500),
    }
    output_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return {"ok": True, "output_path": str(output_path), "songs": len(payload["songs"])}
