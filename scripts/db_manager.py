import sqlite3
import os
import threading
from datetime import datetime
from config import DB_DIR, DB_PATH

# ---------------------------------------------------------------------------
# ONE LOCK FOR ALL DB OPERATIONS
#
# SQLite raises two different error codes:
#   SQLITE_BUSY   (5)  → another OS process holds a file lock   → timeout helps
#   SQLITE_LOCKED (6)  → write conflict inside the same process → timeout does NOT help
#
# asyncio.to_thread() spawns real OS threads.  When two threads call
# update_song_status() at the same time both open separate connections and
# race to write → SQLITE_LOCKED.  A single threading.Lock serialises every
# read/write so only one thread touches the DB at a time, eliminating the race
# entirely without needing a persistent connection pool.
# ---------------------------------------------------------------------------
_DB_LOCK      = threading.Lock()
_initialized  = False


def _get_conn() -> sqlite3.Connection:
    """Open a short-lived connection. check_same_thread=False is required
    because connections are created inside asyncio worker threads."""
    return sqlite3.connect(DB_PATH, timeout=30, check_same_thread=False)


# ---------------------------------------------------------------------------
# INIT
# ---------------------------------------------------------------------------

def init_db():
    """
    Create the DB directory + table and enable WAL mode — but only once.
    Every subsequent call (from any thread) is a no-op via double-checked locking.
    """
    global _initialized
    if _initialized:
        return

    with _DB_LOCK:
        if _initialized:          # another thread may have finished while we waited
            return

        os.makedirs(DB_DIR, exist_ok=True)
        conn   = _get_conn()
        cursor = conn.cursor()

        # WAL: readers never block writers, writers never block readers.
        # Wrapped in try/except — harmless if already set or another process
        # holds a brief lock on the file at startup.
        try:
            cursor.execute("PRAGMA journal_mode=WAL;")
        except sqlite3.OperationalError as e:
            print(f"⚠️  WAL pragma skipped (non-fatal): {e}")

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS pipeline_jobs (
                video_id     TEXT PRIMARY KEY,
                title        TEXT,
                artist       TEXT,
                status       TEXT,
                last_updated TEXT
            )
        ''')
        conn.commit()
        conn.close()

        _initialized = True
        print("✅ Database initialised.")


# ---------------------------------------------------------------------------
# PUBLIC API  (every function acquires _DB_LOCK before touching the file)
# ---------------------------------------------------------------------------

def get_song_status(video_id: str):
    """Return the current pipeline status string, or None if not in DB."""
    with _DB_LOCK:
        conn   = _get_conn()
        cursor = conn.cursor()
        cursor.execute(
            'SELECT status FROM pipeline_jobs WHERE video_id = ?', (video_id,)
        )
        result = cursor.fetchone()
        conn.close()
    return result[0] if result else None


def insert_new_job(video_id: str, title: str, artist: str, status: str):
    """Insert a new song row (or replace if video_id already exists)."""
    with _DB_LOCK:
        conn   = _get_conn()
        cursor = conn.cursor()
        now    = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cursor.execute('''
            INSERT OR REPLACE INTO pipeline_jobs
                (video_id, title, artist, status, last_updated)
            VALUES (?, ?, ?, ?, ?)
        ''', (video_id, title, artist, status, now))
        conn.commit()
        conn.close()

def get_total_video_count() -> int:
    with _DB_LOCK:
        conn = _get_conn()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM pipeline_jobs WHERE status IN ('VIDEO_CREATED', 'UPLOADED')")
        result = cursor.fetchone()
        conn.close()
    return result[0] if result else 0


def update_song_status(video_id: str, status: str):
    """Advance a song to the next pipeline status."""
    with _DB_LOCK:
        conn   = _get_conn()
        cursor = conn.cursor()
        now    = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cursor.execute('''
            UPDATE pipeline_jobs
            SET    status = ?, last_updated = ?
            WHERE  video_id = ?
        ''', (status, now, video_id))
        conn.commit()
        conn.close()
    print(f"✅ DB status updated → {status}")