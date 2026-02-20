import os
import shutil
import sqlite3
import subprocess
from datetime import datetime

# --- CONFIGURATION ---
DB_PATH = os.path.join("Database", "echoforge.db")
ASSETS_DIR = "Assets"
REACT_PUBLIC_DIR = os.path.join("video-engine", "public")
OUTPUT_DIR = "Output"

def get_ready_job():
    """Finds the first song in the database that is ready to be rendered."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT video_id, title, artist FROM processed_songs WHERE status = ?', ('ASSETS_READY',))
    job = cursor.fetchone()
    conn.close()
    return job

def update_status(video_id, new_status):
    """Updates the job queue state."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        UPDATE processed_songs 
        SET status = ?, last_updated = ? 
        WHERE video_id = ?
    ''', (new_status, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), video_id))
    conn.commit()
    conn.close()

def find_asset_folder(title):
    """Locates the specific folder inside Assets/ based on the song title."""
    import glob
    # We look for any folder that ends with the sanitized title
    safe_title = "".join([c for c in title if c.isalnum() or c in " -_"]).strip()
    folders = glob.glob(os.path.join(ASSETS_DIR, f"*-{safe_title}*"))
    return folders[0] if folders else None

def render_video():
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
    
    files_to_stage = ["audio.mp3", "timestamps.json", "metadata.json"]
    for file in files_to_stage:
        src = os.path.join(asset_folder, file)
        dst = os.path.join(REACT_PUBLIC_DIR, file)
        if os.path.exists(src):
            shutil.copy(src, dst)
        else:
            print(f"❌ Missing critical file: {file}")
            return

    # 4. Trigger the Remotion CLI
    print("   ⚙️ Triggering Remotion Renderer (This may take a minute)...")
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    
    # Create a clean filename for the final MP4
    safe_title = "".join([c for c in title if c.isalnum() or c in " -_"]).strip()
    final_video_path = os.path.abspath(os.path.join(OUTPUT_DIR, f"{safe_title}.mp4"))

    # We use subprocess to run the actual NPM command from Python!
    try:
        # npx remotion render <composition_id> <output_file>
        command = [
            "npx", "remotion", "render", 
            "EchoForgeLyricVideo", 
            final_video_path
        ]
        
        # Run the command from inside the video-engine folder
        subprocess.run(command, cwd="video-engine", check=True)
        
        # 5. Success! Update the database
        print(f"\n✅ SUCCESS! Video rendered to: {final_video_path}")
        update_status(video_id, "VIDEO_CREATED")
        
    except subprocess.CalledProcessError as e:
        print(f"\n❌ Render failed: {e}")

if __name__ == "__main__":
    render_video()