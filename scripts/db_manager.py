import sqlite3
import os
from datetime import datetime

# --- CONFIGURATION ---
DB_DIR = "Database"
DB_PATH = os.path.join(DB_DIR, "echoforge.db")

def init_db():
    """
    Creates the SQLite job queue database and table.
    Safe to run multiple times; 'IF NOT EXISTS' prevents data erasure.
    """
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

def get_song_status(video_id: str):
    """
    Checks if a song is currently in the database.
    
    Args:
        video_id (str): The unique YouTube video ID.
        
    Returns:
        str | None: Its status (e.g., 'UPLOADED', 'AUDIO_DOWNLOADED'), 
                    or None if it doesn't exist in the system yet.
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT status FROM processed_songs WHERE video_id = ?', (video_id,))
    result = cursor.fetchone()
    conn.close()
    
    if result:
        return result[0] 
    return None

def insert_new_job(video_id: str, title: str, artist: str, status: str = "AUDIO_DOWNLOADED"):
    """
    Adds a newly discovered song to the pipeline.
    Catches IntegrityErrors to prevent crashing if a duplicate is accidentally sent.
    """
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
        print(f"⚠️ Warning: '{title}' is already in the database! Skipping insert.")
    finally:
        conn.close()

def update_job_status(video_id: str, new_status: str):
    """
    Updates the status of an existing song as it moves through the pipeline.
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        UPDATE processed_songs 
        SET status = ?, last_updated = ? 
        WHERE video_id = ?
    ''', (new_status, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), video_id))
    
    # Check if the update actually found a row to change!
    if cursor.rowcount == 0:
        print(f"⚠️ Warning: Tried to update status to [{new_status}], but video ID '{video_id}' was not found in DB.")
    else:
        print(f"🔄 DB Status updated to: [{new_status}] for video {video_id}")
        
    conn.commit()
    conn.close()

def get_total_video_count():
    """Counts how many videos EchoForge has processed to calculate the background cycle."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM jobs")
    count = cursor.fetchone()[0]
    conn.close()
    return count

if __name__ == "__main__":
    # ==========================================
    # STANDALONE EXECUTION
    # ==========================================
    # Running this file directly just initializes the database safely.
    init_db()
    print(f"🗄️ Database initialized and verified at: {DB_PATH}")