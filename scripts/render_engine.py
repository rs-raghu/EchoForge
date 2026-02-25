import os
import shutil
import sqlite3
import subprocess
import glob
import re
from datetime import datetime

# --- CUSTOM MODULES ---
import db_manager

# --- CONFIGURATION ---
DB_PATH = os.path.join("Database", "echoforge.db")
ASSETS_DIR = "Assets"
REACT_PUBLIC_DIR = os.path.join("video-engine", "public")
OUTPUT_DIR = "Output"

def get_ready_job():
    """
    Queries the database for the first available song that has its assets 
    fully prepared by the Whisper sync engine.
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    try:
        cursor.execute('SELECT video_id, title, artist FROM processed_songs WHERE status = ?', ('ASSETS_READY',))
        return cursor.fetchone()
    finally:
        conn.close()

def clean_folder_name(name: str):
    """
    Matches the EXACT regex used in auto_discovery.py to ensure 
    folder names match perfectly across the pipeline.
    """
    return re.sub(r'[\\/*?:"<>|]', "", name).strip()

def find_asset_folder(title: str):
    """Locates the specific folder inside Assets/ based on the sanitized song title."""
    safe_title = clean_folder_name(title)
    folders = glob.glob(os.path.join(ASSETS_DIR, f"*-{safe_title}*"))
    return folders[0] if folders else None

def render_video():
    """
    The Master Visual Orchestrator.
    Stages the data into the React engine and triggers the Remotion CLI.
    """
    print("🎬 BOOTING RENDER ENGINE...")
    
    # 1. Check the Job Queue
    job = get_ready_job()
    if not job:
        print("💤 No videos are currently in 'ASSETS_READY' status. Waiting for new data.")
        return

    video_id, title, artist = job
    print(f"\n🚀 Found pending render: {title} by {artist}")

    # 2. Locate the Source Assets
    asset_folder = find_asset_folder(title)
    if not asset_folder:
        print(f"❌ Error: Could not find the Asset folder for {title}")
        return

    # 3. Stage the files into the React Engine
    print("   📂 Staging assets into the visual engine...")
    os.makedirs(REACT_PUBLIC_DIR, exist_ok=True)
    
    files_to_stage = ["audio.mp3", "timestamps.json", "metadata.json", "bg.jpg"]
    for file_name in files_to_stage:
        source = os.path.join(asset_folder, file_name) # FIXED: Changed to asset_folder
        destination = os.path.join("video-engine", "public", file_name)
        
        if os.path.exists(source):
            import shutil
            shutil.copy(source, destination)
            print(f"   📂 Staged: {file_name}")
        else:
            print(f"   ❌ Missing asset for render: {file_name}")
            return

    # 4. Trigger the Remotion CLI
    print("   ⚙️ Triggering Remotion Renderer (This may take a minute)...")
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    
    safe_title = clean_folder_name(title)
    final_video_path = os.path.abspath(os.path.join(OUTPUT_DIR, f"{safe_title}.mp4"))

    try:
        command = [
            "npx", "remotion", "render", 
            "EchoForgeLyricVideo", 
            final_video_path
        ]
        
        # shell=True is highly recommended on Windows for npx/npm commands
        use_shell = os.name == 'nt' 
        
        subprocess.run(command, cwd="video-engine", check=True, shell=use_shell)
        
        # 5. Success! Route the update through our master DB Manager
        print(f"\n✅ SUCCESS! Video rendered to: {final_video_path}")
        db_manager.update_job_status(video_id, "VIDEO_CREATED")
        
    except subprocess.CalledProcessError as e:
        print(f"\n❌ Render failed: The Remotion CLI encountered an error. {e}")
    except Exception as e:
        print(f"\n❌ Unexpected System Error: {e}")

if __name__ == "__main__":
    render_video()