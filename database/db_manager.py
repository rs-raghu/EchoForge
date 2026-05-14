import sqlite3
import os
from datetime import datetime

# Assuming you will create utils/logger.py next
from utils.logger import get_logger

log = get_logger(__name__)

# Dynamically set DB path to live right next to this script in the /database folder
DB_PATH = os.path.join(os.path.dirname(__file__), 'echoforge.db')

def init_db():
    """Initializes the new Event-Driven schema."""
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        
        # The main Songs table with Micro/Macro state tracking
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS songs (
                video_id TEXT PRIMARY KEY,
                title TEXT,
                artist TEXT,
                current_macro_state TEXT DEFAULT 'DISCOVERED',
                current_micro_state TEXT DEFAULT 'IDLE',
                target_macro_state TEXT DEFAULT 'STAGED',
                abort_requested BOOLEAN DEFAULT 0,
                workspace_dir TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Settings table for global preferences (fonts, backgrounds)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        ''')
        conn.commit()
    log.info("🗄️ Database initialized successfully.")

# --- THE INSTANT QUEUE ---

def add_discovered_songs(songs_list):
    """Bulk adds songs from a background scraper into the queue."""
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        added_count = 0
        for song in songs_list:
            try:
                cursor.execute('''
                    INSERT INTO songs 
                    (video_id, title, artist, current_macro_state, target_macro_state) 
                    VALUES (?, ?, ?, 'DISCOVERED', 'STAGED')
                ''', (song['video_id'], song['title'], song['artist']))
                added_count += 1
            except sqlite3.IntegrityError:
                # Song is already in the database, skip it
                pass
        conn.commit()
        return added_count

def pop_next_queued_song():
    """Instantly grabs the next trending song without scraping the web."""
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT video_id, title, artist FROM songs 
            WHERE current_macro_state = 'DISCOVERED' 
            ORDER BY rowid ASC LIMIT 1
        ''')
        row = cursor.fetchone()
        
        if row:
            video_id = row[0]
            # Move it out of the background queue and into active Staging
            update_state(video_id, macro='STAGED', micro='IDLE')
            return {"video_id": video_id, "title": row[1], "artist": row[2]}
        return None

# --- STATE MANAGEMENT ---

def update_state(video_id, macro=None, micro=None, workspace_dir=None):
    """Updates the current state of a song."""
    updates = []
    params = []
    
    if macro:
        updates.append("current_macro_state = ?")
        params.append(macro)
    if micro:
        updates.append("current_micro_state = ?")
        params.append(micro)
    if workspace_dir:
        updates.append("workspace_dir = ?")
        params.append(workspace_dir)
        
    if not updates:
        return

    updates.append("updated_at = CURRENT_TIMESTAMP")
    params.append(video_id)
    
    query = f"UPDATE songs SET {', '.join(updates)} WHERE video_id = ?"
    
    with sqlite3.connect(DB_PATH) as conn:
        conn.cursor().execute(query, tuple(params))
        conn.commit()

def set_target_state(video_id, target_macro):
    """Tells the Process Manager (Orchestrator) what the finish line is."""
    with sqlite3.connect(DB_PATH) as conn:
        conn.cursor().execute('''
            UPDATE songs SET 
                target_macro_state = ?, 
                abort_requested = 0, 
                updated_at = CURRENT_TIMESTAMP 
            WHERE video_id = ?
        ''', (target_macro, video_id))
        conn.commit()

# --- THE KILL SWITCH ---

def request_abort(video_id):
    """Flips the kill switch. The Orchestrator will see this and terminate the task."""
    with sqlite3.connect(DB_PATH) as conn:
        conn.cursor().execute('''
            UPDATE songs SET abort_requested = 1 WHERE video_id = ?
        ''', (video_id,))
        conn.commit()

def check_abort(video_id):
    """Used by the Orchestrator to constantly check if it needs to die."""
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT abort_requested FROM songs WHERE video_id = ?', (video_id,))
        row = cursor.fetchone()
        return bool(row[0]) if row else False

# --- UI & DASHBOARD HELPERS ---

def get_active_jobs():
    """Fetches songs for the Telegram /start Dashboard (excluding finished/queued items)."""
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT video_id, title, artist, current_macro_state, current_micro_state 
            FROM songs 
            WHERE current_macro_state NOT IN ('DISCOVERED', 'PUBLISHED', 'DISCARDED', 'UNAVAILABLE')
            ORDER BY updated_at DESC
        ''')
        return [{"video_id": r[0], "title": r[1], "artist": r[2], "macro": r[3], "micro": r[4]} for r in cursor.fetchall()]

def get_song(video_id):
    """Retrieves all data for a single song as a dictionary."""
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM songs WHERE video_id = ?', (video_id,))
        row = cursor.fetchone()
        if not row:
            return None
        
        # Convert the SQLite row tuple into a clean Python dictionary
        cols = [column[0] for column in cursor.description]
        return dict(zip(cols, row))