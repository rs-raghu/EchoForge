import sqlite3
import os
from datetime import datetime

# Define the path to the Database folder
DB_DIR = "Database"
DB_PATH = os.path.join(DB_DIR, "echoforge.db")

def init_db():
    """Creates the database and the table if they don't exist."""
    os.makedirs(DB_DIR, exist_ok=True)
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # We use video_id as the PRIMARY KEY so it is impossible to have duplicates
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS processed_songs (
            video_id TEXT PRIMARY KEY,
            title TEXT,
            artist TEXT,
            processed_date TEXT
        )
    ''')
    
    conn.commit()
    conn.close()
    print(f"🗄️ Database ready at: {DB_PATH}")

def is_processed(video_id):
    """Checks if a song has already been turned into a video."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute('SELECT 1 FROM processed_songs WHERE video_id = ?', (video_id,))
    result = cursor.fetchone()
    
    conn.close()
    return result is not None

def mark_as_processed(video_id, title, artist):
    """Saves a song to the history so we never process it again."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    try:
        cursor.execute('''
            INSERT INTO processed_songs (video_id, title, artist, processed_date)
            VALUES (?, ?, ?, ?)
        ''', (video_id, title, artist, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        conn.commit()
        print(f"💾 Added to history: {title} by {artist}")
    except sqlite3.IntegrityError:
        print(f"⚠️ Warning: '{title}' is already in the database!")
    finally:
        conn.close()

# If you run this file directly, it will just create the empty database.
if __name__ == "__main__":
    init_db()