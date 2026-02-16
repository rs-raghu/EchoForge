import lyricsgenius
import json
import os
import glob
import re

# --- Configuration ---
GENIUS_TOKEN = "PUDY5MFJeq-6t2SMPQMUh7yqN_PPeA2VwwGn_2dOu98XKEDjnAtZB5F7rM5CmVAb" # <--- Paste your token again!

DB_FOLDER = "database/logs"
ASSETS_ROOT = "assets"

def get_latest_job():
    """Finds the most recent trackinfo JSON file."""
    list_of_files = glob.glob(os.path.join(DB_FOLDER, 'trackinfo_*.json'))
    if not list_of_files:
        print("❌ No job files found.")
        return None, None
    latest_file = max(list_of_files, key=os.path.getctime)
    with open(latest_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
    return data, latest_file

def clean_title(title):
    """Removes junk from YouTube titles."""
    title = re.sub(r'\(.*?\)|\[.*?\]', '', title) 
    title = title.replace("Official Video", "").replace("Lyrics", "").replace("Audio", "")
    title = title.split("ft.")[0].split("feat.")[0]
    return title.strip()

def clean_lyrics_text(text):
    """Removes Genius metadata that isn't part of the song."""
    # Remove the first line if it looks like "Song Name Lyrics"
    lines = text.split('\n')
    if "Lyrics" in lines[0]:
        lines = lines[1:]
    
    # Remove the last line if it looks like "123Embed"
    if lines and re.search(r'\d*Embed$', lines[-1]):
        lines = lines[:-1]
        
    return "\n".join(lines).strip()

def fetch_lyrics(title, artist, video_id):
    """Searches Genius with a preference for Romanized lyrics."""
    
    genius = lyricsgenius.Genius(GENIUS_TOKEN)
    genius.verbose = False 
    genius.remove_section_headers = True # Removes [Chorus], [Verse] tags

    clean_track_title = clean_title(title)
    
    # --- STRATEGY 1: Try Romanized Search First ---
    query_romanized = f"{artist} - {clean_track_title} (Romanized)"
    print(f"🔍 Strategy 1: Searching for '{query_romanized}'...")
    song = genius.search_song(query_romanized, artist)

    # --- STRATEGY 2: Standard Search ---
    if not song:
        print(f"⚠️ Romanized version not found. Trying standard: '{clean_track_title}'...")
        song = genius.search_song(clean_track_title, artist)

    if song:
        print(f"✅ Found lyrics for: {song.title}")
        
        # Prepare folder
        folder_path = os.path.join(ASSETS_ROOT, video_id)
        if not os.path.exists(folder_path):
            os.makedirs(folder_path)
            
        lyrics_path = os.path.join(folder_path, "lyrics.txt")
        
        # Clean and Save
        final_lyrics = clean_lyrics_text(song.lyrics)
        
        with open(lyrics_path, "w", encoding='utf-8') as f:
            f.write(final_lyrics)
            
        return lyrics_path
    else:
        print("❌ Lyrics not found on Genius (Standard or Romanized).")
        return None

def update_job_file(json_path, data, lyrics_path):
    data['local_lyrics_path'] = lyrics_path
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4)
    print("📝 Job contract updated with lyrics path.")

if __name__ == "__main__":
    job_data, job_file_path = get_latest_job()
    
    if job_data:
        if "local_audio_path" not in job_data:
            print("⚠️ Warning: Audio not downloaded yet.")

        lyrics_path = fetch_lyrics(job_data['title'], job_data['artist'], job_data['video_id'])
        
        if lyrics_path:
            update_job_file(job_file_path, job_data, lyrics_path)
            print(f"\n🎉 Stage 2 Complete! Romanized Lyrics saved to: {lyrics_path}")