"""
database/db_manager.py

Central SQLite manager for EchoForge V3.

Fixes applied
─────────────
• Bug 3  : WAL mode enabled — prevents "database is locked" errors when the
           bot process and orchestrator process write simultaneously.
• Safety : threading.Lock added — within each process, async bot tasks can
           collide on the same connection; the lock serialises them.
• Chart caching: last_chart_scrape timestamp stored in settings so the UI
           can show "scraped 3 h ago" and prevent redundant API calls.
"""

import os
import sqlite3
import threading
from datetime import datetime

from utils.logger import get_logger

log = get_logger(__name__)

DB_PATH = os.path.join(os.path.dirname(__file__), "echoforge.db")

# One lock per process — guards against concurrent asyncio tasks inside the
# bot process. Does NOT protect across OS processes; WAL mode handles that.
_LOCK = threading.Lock()


# ─── Connection helper ────────────────────────────────────────────────────────

def _get_conn() -> sqlite3.Connection:
    """Open a short-lived WAL-mode connection."""
    conn = sqlite3.connect(DB_PATH, timeout=30, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")   # safe with WAL, faster
    return conn


# ─── Schema ───────────────────────────────────────────────────────────────────

def init_db() -> None:
    """Create tables and enable WAL mode. Safe to call multiple times."""
    with _LOCK:
        conn   = _get_conn()
        cursor = conn.cursor()

        # Main songs table — macro/micro/target state machine
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS songs (
                video_id            TEXT PRIMARY KEY,
                title               TEXT,
                artist              TEXT,
                url                 TEXT,
                current_macro_state TEXT DEFAULT 'DISCOVERED',
                current_micro_state TEXT DEFAULT 'IDLE',
                target_macro_state  TEXT DEFAULT 'STAGED',
                abort_requested     INTEGER DEFAULT 0,
                workspace_dir       TEXT,
                updated_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Migrate older DBs that are missing the url column
        try:
            cursor.execute("ALTER TABLE songs ADD COLUMN url TEXT")
        except sqlite3.OperationalError:
            pass

        # Global key-value settings (fonts, backgrounds, last_chart_scrape, …)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key        TEXT PRIMARY KEY,
                value      TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        conn.commit()
        conn.close()
    log.info("🗄️  Database initialised (WAL mode).")


# ─── Settings helpers ─────────────────────────────────────────────────────────

def get_setting(key: str, default: str | None = None) -> str | None:
    with _LOCK:
        conn   = _get_conn()
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM settings WHERE key=?", (key,))
        row = cursor.fetchone()
        conn.close()
    return row[0] if row else default


def set_setting(key: str, value: str) -> None:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with _LOCK:
        conn = _get_conn()
        conn.execute(
            "INSERT OR REPLACE INTO settings (key, value, updated_at) VALUES (?,?,?)",
            (key, value, now),
        )
        conn.commit()
        conn.close()


# ─── Chart scrape caching ─────────────────────────────────────────────────────

CHART_CACHE_HOURS = 6   # don't re-scrape more often than this


def get_last_scrape_info() -> tuple[str | None, bool]:
    """
    Returns (human_readable_age, is_stale).
    is_stale = True  → safe to scrape again.
    is_stale = False → scraped recently; skip unless user forces it.
    """
    raw = get_setting("last_chart_scrape")
    if not raw:
        return None, True

    try:
        last = datetime.strptime(raw, "%Y-%m-%d %H:%M:%S")
        delta = datetime.now() - last
        hours = delta.total_seconds() / 3600

        if hours < 1:
            age_str = f"{int(delta.total_seconds() / 60)} min ago"
        elif hours < 24:
            age_str = f"{hours:.1f} h ago"
        else:
            age_str = f"{hours / 24:.1f} days ago"

        return age_str, hours >= CHART_CACHE_HOURS

    except ValueError:
        return None, True


def mark_chart_scraped() -> None:
    """Call immediately after a successful scrape."""
    set_setting("last_chart_scrape", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))


# ─── Queue / discovery helpers ────────────────────────────────────────────────

def add_discovered_songs(songs_list: list) -> int:
    """Bulk-insert songs returned by the chart scraper. Returns count added."""
    added = 0
    with _LOCK:
        conn   = _get_conn()
        cursor = conn.cursor()
        for song in songs_list:
            try:
                cursor.execute(
                    """
                    INSERT INTO songs
                        (video_id, title, artist, url,
                         current_macro_state, target_macro_state)
                    VALUES (?, ?, ?, ?, 'DISCOVERED', 'STAGED')
                    """,
                    (
                        song.get("video_id"),
                        song.get("title"),
                        song.get("artist"),
                        song.get("url", f"https://www.youtube.com/watch?v={song.get('video_id', '')}"),
                    ),
                )
                added += 1
            except sqlite3.IntegrityError:
                pass   # already in DB
        conn.commit()
        conn.close()
    return added


def pop_next_queued_song() -> dict | None:
    """
    Atomically grab the next DISCOVERED song and stage it.
    Returns a full song dict or None if the queue is empty.
    """
    with _LOCK:
        conn   = _get_conn()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT video_id, title, artist FROM songs "
            "WHERE current_macro_state='DISCOVERED' ORDER BY rowid ASC LIMIT 1"
        )
        row = cursor.fetchone()
        if row:
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            cursor.execute(
                "UPDATE songs SET current_macro_state='STAGED', "
                "target_macro_state='STAGED', updated_at=? WHERE video_id=?",
                (now, row[0]),
            )
            conn.commit()
        conn.close()

    if not row:
        return None
    return get_song(row[0])


def get_queue_count() -> int:
    """Return number of songs still waiting as DISCOVERED."""
    with _LOCK:
        conn   = _get_conn()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT COUNT(*) FROM songs WHERE current_macro_state='DISCOVERED'"
        )
        row = cursor.fetchone()
        conn.close()
    return row[0] if row else 0


# ─── State management ─────────────────────────────────────────────────────────

def update_state(
    video_id: str,
    macro: str | None   = None,
    micro: str | None   = None,
    workspace_dir: str  | None = None,
) -> None:
    """Update one or more fields on a song row."""
    parts, params = [], []
    if macro:
        parts.append("current_macro_state=?")
        params.append(macro)
    if micro:
        parts.append("current_micro_state=?")
        params.append(micro)
    if workspace_dir:
        parts.append("workspace_dir=?")
        params.append(workspace_dir)
    if not parts:
        return
    parts.append("updated_at=CURRENT_TIMESTAMP")
    params.append(video_id)

    with _LOCK:
        conn = _get_conn()
        conn.execute(
            f"UPDATE songs SET {', '.join(parts)} WHERE video_id=?",
            tuple(params),
        )
        conn.commit()
        conn.close()


def set_target_state(video_id: str, target_macro: str) -> None:
    """Tell the orchestrator what the finish line is and clear any abort flag."""
    with _LOCK:
        conn = _get_conn()
        conn.execute(
            "UPDATE songs SET target_macro_state=?, abort_requested=0, "
            "updated_at=CURRENT_TIMESTAMP WHERE video_id=?",
            (target_macro, video_id),
        )
        conn.commit()
        conn.close()


# ─── Kill switch ──────────────────────────────────────────────────────────────

def request_abort(video_id: str) -> None:
    with _LOCK:
        conn = _get_conn()
        conn.execute(
            "UPDATE songs SET abort_requested=1 WHERE video_id=?", (video_id,)
        )
        conn.commit()
        conn.close()


def check_abort(video_id: str) -> bool:
    with _LOCK:
        conn   = _get_conn()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT abort_requested FROM songs WHERE video_id=?", (video_id,)
        )
        row = cursor.fetchone()
        conn.close()
    return bool(row[0]) if row else False


# ─── Dashboard helpers ────────────────────────────────────────────────────────

def get_active_jobs() -> list:
    """All songs that are in-flight (not DISCOVERED, PUBLISHED, or DISCARDED)."""
    with _LOCK:
        conn   = _get_conn()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT video_id, title, artist,
                   current_macro_state, current_micro_state
            FROM   songs
            WHERE  current_macro_state NOT IN
                   ('DISCOVERED', 'PUBLISHED', 'DISCARDED', 'UNAVAILABLE')
            ORDER  BY updated_at DESC
            """
        )
        rows = cursor.fetchall()
        conn.close()
    return [
        {"video_id": r[0], "title": r[1], "artist": r[2],
         "macro": r[3], "micro": r[4]}
        for r in rows
    ]


def get_song(video_id: str) -> dict | None:
    """Full song row as a dict, or None."""
    with _LOCK:
        conn   = _get_conn()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM songs WHERE video_id=?", (video_id,))
        row = cursor.fetchone()
        if not row:
            conn.close()
            return None
        cols = [c[0] for c in cursor.description]
        conn.close()
    return dict(zip(cols, row))
