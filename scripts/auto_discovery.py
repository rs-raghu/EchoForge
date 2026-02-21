import os
import json
import re
from datetime import datetime
import yt_dlp

# --- CUSTOM MODULES ---
from yt_scrapper import scrape_top_50
import db_manager
from lyrics_fetcher import fetch_lyrics

# --- CONFIGURATION ---
ASSETS_DIR = "Assets"

# ==========================================
# 1. AUDIO FORGE (yt-dlp)
# ==========================================
def download_audio(youtube_url: str, output_folder: str, filename: str = "audio"):
    """
    Downloads the highest quality audio stream directly into the target folder.
    
    Args:
        youtube_url (str): The target YouTube video URL.
        output_folder (str): The directory to save the mp3.
        filename (str): The base name for the output file.
        
    Returns:
        str | None: The absolute path to the downloaded .mp3, or None if failed.
    """
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
def clean_folder_name(name: str):
    """
    Sanitizes strings by removing OS-illegal characters for safe folder creation.
    """
    return re.sub(r'[\\/*?:"<>|]', "", name).strip()

# ==========================================
# 3. THE MASTER PIPELINE
# ==========================================
def run_discovery_pipeline():
    """
    Executes the first phase of the EchoForge automation pipeline:
    1. Initializes DB.
    2. Scrapes Top 50 Charts.
    3. Identifies the highest-ranking unprocessed song.
    4. Downloads the MP3 audio.
    5. Fetches and sanitizes the official Romanized lyrics.
    6. Logs the job to the database.
    """
    print("🚀 STARTING ECHOFORGE DISCOVERY PIPELINE 🚀")
    
    # Step A: Ensure DB is ready
    db_manager.init_db()
    
    # Step B: Fetch the freshest data from YouTube Charts
    print("\n[1/5] Fetching Live Charts...")
    top_50 = scrape_top_50()
    
    if not top_50:
        print("❌ Pipeline halted: Could not retrieve charts.")
        return
        
    print("\n[2/5] Analyzing Database for Winner...")
    winner = None
    
    # Define statuses that indicate a song is already being (or has been) processed
    active_statuses = ["AUDIO_DOWNLOADED", "LYRICS_FETCHED", "ASSETS_READY", "VIDEO_CREATED", "UPLOADED"]
    
    # Step C: Find the #1 song that is NOT currently in the pipeline
    for song in top_50:
        current_status = db_manager.get_song_status(song['video_id'])
        
        if current_status in active_statuses:
            print(f"   ⏭️ Skipping '{song['title']}' (Status: {current_status})")
        else:
            winner = song
            break
            
    if not winner:
        print("\n⚠️ Pipeline halted: All top 50 songs are already in the pipeline or finished!")
        return
        
    print(f"\n🏆 WINNER SELECTED: {winner['title']} by {winner['artist']}")
    
    # Step D: Create the specific Asset Folder
    print("\n[3/5] Creating Asset Workspace...")
    today_date = datetime.now().strftime("%Y-%m-%d")
    safe_title = clean_folder_name(winner['title'])
    
    folder_name = f"{today_date}-{safe_title}"
    workspace_dir = os.path.join(ASSETS_DIR, folder_name)
    
    os.makedirs(workspace_dir, exist_ok=True)
    print(f"📁 Workspace created at: {workspace_dir}")
    
    # Step E: Download the Audio
    print("\n[4/5] Extracting Audio...")
    audio_path = download_audio(winner['url'], workspace_dir, filename="audio")
    
    if audio_path:
        # Step F: Fetch the Official Romanized Lyrics
        print("\n[5/5] Fetching Official Lyrics...")
        lyrics_path = fetch_lyrics(winner['title'], winner['artist'], workspace_dir)
        
        # Determine the final database status for this phase
        final_status = "LYRICS_FETCHED" if lyrics_path else "AUDIO_ONLY"
        
        # Step G: Lock it into the Job Queue
        db_manager.insert_new_job(winner['video_id'], winner['title'], winner['artist'], status=final_status)
        
        # Save the metadata for the video engine to consume later
        winner['status'] = final_status 
        metadata_path = os.path.join(workspace_dir, "metadata.json")
        
        with open(metadata_path, 'w', encoding='utf-8') as f:
            json.dump(winner, f, indent=4, ensure_ascii=False)
            
        print("\n🎉 DISCOVERY PIPELINE COMPLETE! 🎉")
        print(f"📁 Workspace: {workspace_dir}")
        print(f"🎵 Audio: audio.mp3")
        if lyrics_path:
            print(f"📄 Lyrics: lyrics.txt")
    else:
        print("\n❌ Pipeline failed during audio extraction. Database not updated.")

if __name__ == "__main__":
    run_discovery_pipeline()