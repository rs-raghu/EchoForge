import sqlite3
import os
from datetime import datetime

# --- CONFIGURATION ---
DB_DIR = "Database"
DB_PATH = os.path.join(DB_DIR, "echoforge.db")

def init_db():
    """Creates the SQLite job queue database and table."""
    os.makedirs(DB_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS processed_songs (
            video_id TEXT PRIMARY KEY,
            title TEXT,
            artist TEXT,
            status TEXT,
            last_updated TEXT
        )
    ''')
    conn.commit()
    conn.close()

def get_song_status(video_id):
    """
    Checks if a song is in the DB.
    Returns its status (e.g., 'UPLOADED', 'AUDIO_DOWNLOADED'), or None if it doesn't exist.
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT status FROM processed_songs WHERE video_id = ?', (video_id,))
    result = cursor.fetchone()
    conn.close()
    
    if result:
        return result[0] # Returns the status string
    return None

def insert_new_job(video_id, title, artist, status="AUDIO_DOWNLOADED"):
    """Adds a newly discovered song to the pipeline."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    try:
        cursor.execute('''
            INSERT INTO processed_songs (video_id, title, artist, status, last_updated)
            VALUES (?, ?, ?, ?, ?)
        ''', (video_id, title, artist, status, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        conn.commit()
        print(f"💾 Logged to DB: [{status}] {title} by {artist}")
    except sqlite3.IntegrityError:
        print(f"⚠️ Warning: '{title}' is already in the database!")
    finally:
        conn.close()

def update_job_status(video_id, new_status):
    """Updates the status of an existing song as it moves through the video/upload pipeline."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        UPDATE processed_songs 
        SET status = ?, last_updated = ? 
        WHERE video_id = ?
    ''', (new_status, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), video_id))
    conn.commit()
    conn.close()
    print(f"🔄 DB Status updated to: [{new_status}] for video {video_id}")

if __name__ == "__main__":
    # Running this file directly just initializes the empty database
    init_db()
    print(f"🗄️ Database initialized at: {DB_PATH}")