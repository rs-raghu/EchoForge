import os
import re
import json
from datetime import datetime
from yt_scrapper import scrape_top_50
import db_manager
from config import ASSETS_DIR

def clean_folder_name(name: str):
    """Sanitizes strings by removing OS-illegal characters for safe folder creation."""
    return re.sub(r'[\\/*?:"<>|]', "", name).strip()

def create_workspace(song_data: dict, suffix=""):
    """Creates the asset folder and drops the metadata.json inside it."""
    today_date = datetime.now().strftime("%Y-%m-%d")
    safe_title = clean_folder_name(song_data['title'])
    
    if suffix:
        folder_name = f"{today_date}-{safe_title}-{suffix}"
    else:
        folder_name = f"{today_date}-{safe_title}"
        
    workspace_dir = os.path.join(ASSETS_DIR, folder_name)
    os.makedirs(workspace_dir, exist_ok=True)
    print(f"✅ Workspace created at: {workspace_dir}")
    
    # Save the metadata.json directly inside the new folder
    metadata_path = os.path.join(workspace_dir, "metadata.json")
    with open(metadata_path, 'w', encoding='utf-8') as f:
        json.dump(song_data, f, indent=4, ensure_ascii=False)
    print(f"📄 Metadata saved to: {metadata_path}")
        
    return workspace_dir

def get_top_song(skip_count=0):
    """Scrapes Top 50, filters processed songs, and returns the selected song data."""
    print(f"🚀 STARTING ECHOFORGE DISCOVERY (Skipping {skip_count} valid songs) 🚀")
    
    db_manager.init_db()
    
    print("\n[1/2] Fetching Live Charts...")
    top_50 = scrape_top_50()
    
    if not top_50 or len(top_50) == 0:
        print("❌ Pipeline halted: Could not retrieve charts.")
        return None
        
    print("\n[2/2] Analyzing Database for Valid Songs...")
    active_statuses = ["AUDIO_DOWNLOADED", "LYRICS_FETCHED", "ASSETS_READY", "VIDEO_CREATED", "UPLOADED", "UNAVAILABLE", "DISCARDED"]
    
    valid_songs = []
    
    for song in top_50:
        current_status = db_manager.get_song_status(song['video_id'])
        if current_status not in active_statuses:
            valid_songs.append(song)
            
    if skip_count >= len(valid_songs):
        print(f"\n⚠️ Pipeline halted: No more valid songs available at skip index {skip_count}.")
        return None
        
    winner = valid_songs[skip_count]
    print(f"\n🏆 SELECTION LOCKED: {winner['title']} by {winner['artist']}")
    
    return winner