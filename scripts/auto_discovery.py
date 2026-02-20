import os
import json
import re
from datetime import datetime
import yt_dlp

# Import our custom modules
from yt_scrapper import scrape_top_50
import db_manager

# --- CONFIGURATION ---
ASSETS_DIR = "Assets"

# ==========================================
# 1. AUDIO FORGE (yt-dlp)
# ==========================================
def download_audio(youtube_url, output_folder, filename="audio"):
    """Downloads the MP3 directly into the specific Asset folder."""
    print(f"\n🎵 Downloading audio from: {youtube_url}")
    
    ydl_opts = {
        'format': 'bestaudio/best',
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }],
        'outtmpl': os.path.join(output_folder, f"{filename}.%(ext)s"),
        'quiet': False,
        'no_warnings': True,
        'nocheckcertificate': True
    }
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([youtube_url])
        return os.path.join(output_folder, f"{filename}.mp3")
    except Exception as e:
        print(f"❌ Audio download failed: {e}")
        return None

# ==========================================
# 2. HELPER FUNCTIONS
# ==========================================
def clean_folder_name(name):
    """Removes illegal characters (\ / : * ? " < > |) for safe folder creation."""
    return re.sub(r'[\\/*?:"<>|]', "", name).strip()

# ==========================================
# 3. THE MASTER PIPELINE
# ==========================================
def run_discovery_pipeline():
    print("🚀 STARTING ECHOFORGE DISCOVERY PIPELINE 🚀")
    
    # Step A: Ensure DB is ready
    db_manager.init_db()
    
    # Step B: Fetch the freshest data from YouTube Charts
    print("\n[1/4] Fetching Live Charts...")
    top_50 = scrape_top_50()
    
    if not top_50:
        print("❌ Pipeline halted: Could not retrieve charts.")
        return
        
    print("\n[2/4] Analyzing Database for Winner...")
    winner = None
    
    # Step C: Find the #1 song that is NOT currently in the pipeline
    for song in top_50:
        current_status = db_manager.get_song_status(song['video_id'])
        
        # If it has any of these statuses, we skip it and look at the next song
        if current_status in ["AUDIO_DOWNLOADED", "VIDEO_CREATED", "UPLOADED"]:
            print(f"   ⏭️ Skipping '{song['title']}' (Status: {current_status})")
        else:
            winner = song
            break
            
    if not winner:
        print("\n⚠️ Pipeline halted: All top 50 songs are already in the pipeline or finished!")
        return
        
    print(f"\n🏆 WINNER SELECTED: {winner['title']} by {winner['artist']}")
    
    # Step D: Create the specific Asset Folder (e.g., "Assets/2026-02-20-Espresso")
    print("\n[3/4] Creating Asset Workspace...")
    today_date = datetime.now().strftime("%Y-%m-%d")
    safe_title = clean_folder_name(winner['title'])
    
    folder_name = f"{today_date}-{safe_title}"
    workspace_dir = os.path.join(ASSETS_DIR, folder_name)
    
    os.makedirs(workspace_dir, exist_ok=True)
    print(f"📁 Workspace created at: {workspace_dir}")
    
    # Step E: Download the Audio
    print("\n[4/4] Extracting Audio...")
    audio_path = download_audio(winner['url'], workspace_dir, filename="audio")
    
    if audio_path:
        # Step F: Add it to the Job Queue with its initial status
        db_manager.insert_new_job(winner['video_id'], winner['title'], winner['artist'], status="AUDIO_DOWNLOADED")
        
        # Save a mini-JSON file in the workspace so the video engine knows what text to render
        metadata_path = os.path.join(workspace_dir, "metadata.json")
        winner['status'] = "AUDIO_DOWNLOADED" # Inject status into the local metadata
        
        with open(metadata_path, 'w', encoding='utf-8') as f:
            json.dump(winner, f, indent=4, ensure_ascii=False)
            
        print("\n🎉 PIPELINE COMPLETE! 🎉")
        print(f"🎵 Audio: {audio_path}")
        print(f"📄 Metadata: {metadata_path}")
    else:
        print("\n❌ Pipeline failed during audio extraction. Database not updated.")

if __name__ == "__main__":
    run_discovery_pipeline()