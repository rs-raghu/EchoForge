import os
import sqlite3
import glob
import re
from datetime import datetime

# --- IMPORT OUR MICROSERVICES ---
import db_manager
import auto_discovery
import sync_engine
import render_engine

# --- CONFIGURATION ---
DB_PATH = os.path.join("Database", "echoforge.db")
ASSETS_DIR = "Assets"

def clean_folder_name(name: str):
    """Sanitizes folder names to match the exact regex across the system."""
    return re.sub(r'[\\/*?:"<>|]', "", name).strip()

def get_job_by_status(status: str):
    """Queries the database for a song waiting in a specific state."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    try:
        cursor.execute('SELECT video_id, title, artist FROM processed_songs WHERE status = ?', (status,))
        return cursor.fetchone()
    finally:
        conn.close()

def find_asset_folder(title: str):
    """Locates the workspace folder for a specific song."""
    safe_title = clean_folder_name(title)
    folders = glob.glob(os.path.join(ASSETS_DIR, f"*-{safe_title}*"))
    return folders[0] if folders else None

def run_echoforge_cycle():
    """Executes one complete waterfall cycle of the EchoForge pipeline."""
    print(f"\n[{datetime.now().strftime('%H:%M:%S')}] 🤖 WAKING UP ECHOFORGE MASTER CONTROLLER...")
    
    # ---------------------------------------------------------
    # PHASE 1: DISCOVERY & ACQUISITION
    # ---------------------------------------------------------
    print("\n=======================================")
    print("PHASE 1: DISCOVERY & DOWNLOAD")
    print("=======================================")
    auto_discovery.run_discovery_pipeline()

    # ---------------------------------------------------------
    # PHASE 2: WHISPER ALIGNMENT
    # ---------------------------------------------------------
    print("\n=======================================")
    print("PHASE 2: WHISPER ALIGNMENT")
    print("=======================================")
    # Look for the baton passed by auto_discovery (LYRICS_FETCHED)
    sync_job = get_job_by_status("LYRICS_FETCHED")
    
    if sync_job:
        video_id, title, artist = sync_job
        folder = find_asset_folder(title)
        if folder:
            sync_engine.align_audio_and_text(folder)
        else:
            print(f"❌ Master Error: Could not find workspace folder for {title}")
    else:
        print("💤 No songs currently waiting for Whisper synchronization.")

    # ---------------------------------------------------------
    # PHASE 3: VISUAL RENDERING
    # ---------------------------------------------------------
    print("\n=======================================")
    print("PHASE 3: REMOTION RENDER")
    print("=======================================")
    # render_engine already has its own internal state-checking logic for ASSETS_READY!
    render_engine.render_video()

    print("\n=======================================")
    print("🏁 DAILY PIPELINE CYCLE COMPLETE 🏁")
    print("=======================================")

if __name__ == "__main__":
    # Ensure the DB exists before starting
    db_manager.init_db()
    
    print("🔥 ECHOFORGE DAILY RUN INITIATED 🔥")
    
    # Run the assembly line exactly once
    run_echoforge_cycle()
    
    print("\n✅ Script finished successfully. Shutting down.")