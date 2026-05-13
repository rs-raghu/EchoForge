"""
db_manager.py

Central SQLite database manager for EchoForge.

Tables
──────
pipeline_jobs   — one row per song; tracks pipeline stage.
weekly_charts   — top-100 chart cache; refreshed on Sunday 12 PM PST rule.
user_settings   — key/value store for bot preferences (fonts, pinned BG, etc.).

Changes
───────
• Bug 5  : Added get_assets_ready_job() — public replacement for the private
            _DB_LOCK / _get_conn() pattern used directly in render_engine.py.
• Bug 8  : Added get_statuses_for_ids() — one batch query replaces N individual
            get_song_status() calls in auto_discovery.get_top_song().
• Feature 4 : Added check_duplicate_title_artist() — normalised title+artist
               dedup across different video IDs.
• Feature 9 : Added get_job_details() — full row lookup for /retry command.
• Added delete_setting() for clearing pinned background (/changebg reset).
• pipeline_jobs now stores title_norm + artist_norm columns for dedup.
"""

import os
import re
import sqlite3
import threading
from datetime import datetime

from config import DB_DIR, DB_PATH
from logger import get_logger

log = get_logger(__name__)

_DB_LOCK     = threading.Lock()
_initialized = False


# ─── Internal helpers ─────────────────────────────────────────────────────────

def _get_conn() -> sqlite3.Connection:
    return sqlite3.connect(DB_PATH, timeout=30, check_same_thread=False)


def _normalize(text: str) -> str:
    """Lowercase + strip punctuation for fuzzy duplicate comparison."""
    return re.sub(r"[^\w\s]", "", text.lower()).strip()


# ─── Initialisation ───────────────────────────────────────────────────────────

def init_db() -> None:
    """Create the DB directory, enable WAL mode, and create all tables (once)."""
    global _initialized
    if _initialized:
        return

    with _DB_LOCK:
        if _initialized:
            return

        os.makedirs(DB_DIR, exist_ok=True)
        conn   = _get_conn()
        cursor = conn.cursor()

        try:
            cursor.execute("PRAGMA journal_mode=WAL;")
        except sqlite3.OperationalError as exc:
            log.warning("⚠️  WAL pragma skipped (non-fatal): %s", exc)

        # pipeline_jobs includes title_norm / artist_norm for duplicate detection
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS pipeline_jobs (
                video_id     TEXT PRIMARY KEY,
                title        TEXT,
                artist       TEXT,
                status       TEXT,
                title_norm   TEXT,
                artist_norm  TEXT,
                last_updated TEXT
            )
        """)

        # Migrate existing DBs that predate the norm columns (safe: fails silently)
        for col in ("title_norm", "artist_norm"):
            try:
                cursor.execute(f"ALTER TABLE pipeline_jobs ADD COLUMN {col} TEXT")
            except sqlite3.OperationalError:
                pass   # column already exists

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS weekly_charts (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                rank         INTEGER,
                title        TEXT,
                artist       TEXT,
                video_id     TEXT,
                url          TEXT,
                weekly_views INTEGER,
                search_query TEXT,
                scraped_at   TEXT
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_settings (
                key        TEXT PRIMARY KEY,
                value      TEXT,
                updated_at TEXT
            )
        """)

        conn.commit()
        conn.close()
        _initialized = True
        log.info("✅ Database initialised.")


# ─── pipeline_jobs API ────────────────────────────────────────────────────────

def get_song_status(video_id: str) -> str | None:
    with _DB_LOCK:
        conn   = _get_conn()
        cursor = conn.cursor()
        cursor.execute("SELECT status FROM pipeline_jobs WHERE video_id = ?", (video_id,))
        row = cursor.fetchone()
        conn.close()
    return row[0] if row else None


def insert_new_job(video_id: str, title: str, artist: str, status: str) -> None:
    with _DB_LOCK:
        conn   = _get_conn()
        cursor = conn.cursor()
        now    = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cursor.execute(
            """
            INSERT OR REPLACE INTO pipeline_jobs
                (video_id, title, artist, status, title_norm, artist_norm, last_updated)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (video_id, title, artist, status,
             _normalize(title), _normalize(artist), now),
        )
        conn.commit()
        conn.close()


def update_song_status(video_id: str, status: str) -> None:
    with _DB_LOCK:
        conn   = _get_conn()
        cursor = conn.cursor()
        now    = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cursor.execute(
            "UPDATE pipeline_jobs SET status=?, last_updated=? WHERE video_id=?",
            (status, now, video_id),
        )
        conn.commit()
        conn.close()
    log.info("✅ DB status → %s", status)


def get_total_video_count() -> int:
    with _DB_LOCK:
        conn   = _get_conn()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT COUNT(*) FROM pipeline_jobs WHERE status IN ('VIDEO_CREATED','UPLOADED')"
        )
        row = cursor.fetchone()
        conn.close()
    return row[0] if row else 0


def get_status_counts() -> dict:
    _STAGE_ORDER = [
        "UPLOADED", "VIDEO_CREATED", "ASSETS_READY",
        "LYRICS_READY", "LYRICS_FETCHED", "AUDIO_FETCHED",
        "PENDING", "UNAVAILABLE", "DISCARDED", "FAILED",
    ]
    with _DB_LOCK:
        conn   = _get_conn()
        cursor = conn.cursor()
        cursor.execute("SELECT status, COUNT(*) FROM pipeline_jobs GROUP BY status")
        rows = cursor.fetchall()
        conn.close()
    raw     = {r[0]: r[1] for r in rows}
    ordered = {}
    for stage in _STAGE_ORDER:
        if stage in raw:
            ordered[stage] = raw.pop(stage)
    ordered.update(raw)
    return ordered


def get_recent_jobs(limit: int = 15) -> list:
    with _DB_LOCK:
        conn   = _get_conn()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT title, artist, status, last_updated FROM pipeline_jobs "
            "ORDER BY last_updated DESC LIMIT ?",
            (limit,),
        )
        rows = cursor.fetchall()
        conn.close()
    return [{"title": r[0] or "", "artist": r[1] or "",
             "status": r[2] or "", "updated": r[3] or ""} for r in rows]


# ─── Bug 5: public replacement for private DB access in render_engine.py ──────

def get_assets_ready_job() -> tuple | None:
    """
    Return (video_id, title, artist) for the first ASSETS_READY job, or None.
    Replaces the render_engine pattern of accessing _DB_LOCK/_get_conn directly.
    """
    with _DB_LOCK:
        conn   = _get_conn()
        cursor = conn.cursor()
        try:
            cursor.execute(
                "SELECT video_id, title, artist FROM pipeline_jobs "
                "WHERE status = ? LIMIT 1",
                ("ASSETS_READY",),
            )
            row = cursor.fetchone()
        except Exception as exc:
            log.error("❌ get_assets_ready_job DB error: %s", exc)
            row = None
        finally:
            conn.close()
    return row


# ─── Bug 8: batch status lookup (replaces N individual queries in discovery) ──

def get_statuses_for_ids(video_ids: list) -> dict:
    """
    Return {video_id: status} for all given IDs in a single SQL query.
    IDs absent from the DB are simply not in the returned dict.
    """
    if not video_ids:
        return {}
    placeholders = ",".join("?" * len(video_ids))
    with _DB_LOCK:
        conn   = _get_conn()
        cursor = conn.cursor()
        cursor.execute(
            f"SELECT video_id, status FROM pipeline_jobs "
            f"WHERE video_id IN ({placeholders})",
            video_ids,
        )
        rows = cursor.fetchall()
        conn.close()
    return {r[0]: r[1] for r in rows}


# ─── Feature 4: duplicate song detection ──────────────────────────────────────

def check_duplicate_title_artist(title: str, artist: str) -> dict | None:
    """
    Check if a song with the same normalised title + artist already exists,
    regardless of video_id.  Returns existing job dict or None.

    Normalisation: lowercase + strip punctuation, so "Don't Stop Me Now" and
    "dont stop me now" are treated as duplicates.
    """
    t_norm = _normalize(title)
    a_norm = _normalize(artist)
    with _DB_LOCK:
        conn   = _get_conn()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT video_id, title, artist, status FROM pipeline_jobs "
            "WHERE title_norm=? AND artist_norm=? LIMIT 1",
            (t_norm, a_norm),
        )
        row = cursor.fetchone()
        conn.close()
    if not row:
        return None
    return {"video_id": row[0], "title": row[1], "artist": row[2], "status": row[3]}


# ─── Feature 9: full job lookup for /retry ────────────────────────────────────

def get_job_details(video_id: str) -> dict | None:
    """Return the full pipeline job row as a dict, or None if not found."""
    with _DB_LOCK:
        conn   = _get_conn()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT video_id, title, artist, status FROM pipeline_jobs WHERE video_id=?",
            (video_id,),
        )
        row = cursor.fetchone()
        conn.close()
    if not row:
        return None
    return {"video_id": row[0], "title": row[1], "artist": row[2], "status": row[3]}


# ─── weekly_charts API ────────────────────────────────────────────────────────

def cache_charts(songs: list) -> None:
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    with _DB_LOCK:
        conn   = _get_conn()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM weekly_charts")
        cursor.executemany(
            "INSERT INTO weekly_charts "
            "(rank,title,artist,video_id,url,weekly_views,search_query,scraped_at) "
            "VALUES (?,?,?,?,?,?,?,?)",
            [
                (s.get("rank", 0), s.get("title", ""), s.get("artist", ""),
                 s.get("video_id", ""), s.get("url", ""), s.get("weekly_views", 0),
                 s.get("search_query", ""), now)
                for s in songs
            ],
        )
        conn.commit()
        conn.close()
    log.info("✅ Cached %d songs (scraped_at=%s UTC).", len(songs), now)


def get_cached_charts() -> tuple[list, str | None]:
    with _DB_LOCK:
        conn   = _get_conn()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT rank,title,artist,video_id,url,weekly_views,search_query,scraped_at "
            "FROM weekly_charts ORDER BY rank ASC"
        )
        rows = cursor.fetchall()
        conn.close()
    if not rows:
        return [], None
    songs = [{"rank": r[0], "title": r[1], "artist": r[2], "video_id": r[3],
              "url": r[4], "weekly_views": r[5], "search_query": r[6]} for r in rows]
    return songs, rows[0][7]


# ─── user_settings API ────────────────────────────────────────────────────────

def get_setting(key: str, default: str | None = None) -> str | None:
    with _DB_LOCK:
        conn   = _get_conn()
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM user_settings WHERE key=?", (key,))
        row = cursor.fetchone()
        conn.close()
    return row[0] if row else default


def set_setting(key: str, value: str) -> None:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with _DB_LOCK:
        conn   = _get_conn()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT OR REPLACE INTO user_settings (key,value,updated_at) VALUES (?,?,?)",
            (key, value, now),
        )
        conn.commit()
        conn.close()
    log.info("✅ Setting: %s = %s", key, value)


def delete_setting(key: str) -> None:
    """Remove a user setting — used by /changebg reset to clear pinned_bg."""
    with _DB_LOCK:
        conn   = _get_conn()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM user_settings WHERE key=?", (key,))
        conn.commit()
        conn.close()
    log.info("✅ Setting deleted: %s", key)


def get_font_paths() -> dict:
    return {
        "title":  get_setting("title_font"),
        "artist": get_setting("artist_font"),
        "lyrics": get_setting("lyrics_font"),
    }