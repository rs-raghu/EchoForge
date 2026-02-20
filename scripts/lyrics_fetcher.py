import os
import re
import json
import glob
from datetime import datetime
import lyricsgenius
from anyascii import anyascii

# --- CONFIGURATION ---
GENIUS_ACCESS_TOKEN = "A3_0t0cObi9eLcPYkX7mAoSmiabeBrxYaF0n-n9P5hXcczXG3ncRWLio7Z4LiE9E" # ⚠️ Keep your token here
genius = lyricsgenius.Genius(GENIUS_ACCESS_TOKEN)
genius.remove_section_headers = True
genius.verbose = False 
genius.remove_dict = True 

def clean_lyrics_text(raw_lyrics):
    """
    Heuristic filter to clean the messy text returned by the Genius API,
    including rebuilding fragmented sentences and broken syllables.
    """
    # 1. Standard Genius cleanup
    clean_text = re.sub(r'^.*Lyrics', '', raw_lyrics, count=1)
    clean_text = re.sub(r'\d*(\.\d+)?K?M?Embed$', '', clean_text)
    clean_text = re.sub(r'Embed$', '', clean_text)
    clean_text = re.sub(r'\[.*?\]', '', clean_text)
    
    # 2. THE SENTENCE REBUILDER (Fixes broken K-Pop formatting)
    # Fixes ad-libs broken across multiple lines: "(\nAh\n)" -> "(Ah)"
    clean_text = re.sub(r'\(\s*\n\s*', '(', clean_text)
    clean_text = re.sub(r'\s*\n\s*\)', ')', clean_text)
    
    # Glues lowercase fragments to the previous line: "Eo\nduwojin" -> "Eoduwojin"
    clean_text = re.sub(r'\n\s*([a-z])', r'\1', clean_text)
    
    # Removes double spaces created by gluing words together
    clean_text = re.sub(r' +', ' ', clean_text)
    
    # 3. Final polish (remove blank lines)
    clean_text = "\n".join([line.strip() for line in clean_text.splitlines() if line.strip()])
    
    return clean_text

def fetch_lyrics(title, artist, output_folder):
    """
    Uses a Waterfall Search to guarantee romanized (English alphabet) lyrics.
    """
    print(f"\n📝 Fetching lyrics for: '{title}' by {artist}...")
    
    try:
        song = None
        
        # --- STAGE 1: THE GENIUS HACK ---
        # We explicitly ask Genius if a fan-made "Romanized" version exists.
        print("   🔍 Searching for official Romanized version...")
        romanized_query = f"{title} Romanized"
        song = genius.search_song(romanized_query, artist)
        
        # --- STAGE 2: THE STANDARD FALLBACK ---
        # If no romanized version exists (e.g. it's already an English song), search normally.
        if not song:
            print("   ⚠️ No Romanized page found. Searching original title...")
            song = genius.search_song(title, artist)
            
        if song and song.lyrics:
            print("   ✅ Lyrics found! Cleaning formatting...")
            
            # Clean the Genius formatting [Chorus], Embed numbers, etc.
            cleaned_text = clean_lyrics_text(song.lyrics)
            
            # --- STAGE 3: THE BRUTE-FORCE FALLBACK ---
            # We pass the clean text through anyascii. 
            # - If it's English (Espresso), it does absolutely nothing.
            # - If it's Korean (안녕하세요), it forces it to "annyeonghaseyo".
            # - If it's Spanish (Corazón), it safely changes it to "Corazon".
            final_romanized_text = anyascii(cleaned_text)
            
            os.makedirs(output_folder, exist_ok=True)
            
            lyrics_path = os.path.join(output_folder, "lyrics.txt")
            with open(lyrics_path, 'w', encoding='utf-8') as f:
                f.write(final_romanized_text)
                
            print(f"   💾 Saved Romanized lyrics to: {lyrics_path}")
            return lyrics_path
        else:
            print("   ❌ Lyrics not found on Genius.")
            return None
            
    except Exception as e:
        print(f"   ❌ Error communicating with Genius API: {e}")
        return None

if __name__ == "__main__":
    # ==========================================
    # STANDALONE TEST
    # ==========================================
    print("🔍 Looking for the latest YouTube Charts JSON...")
    
    json_folder = os.path.join("Database", "JSON")
    json_files = glob.glob(os.path.join(json_folder, "*.json"))
    
    if not json_files:
        print("❌ No JSON files found in Database/JSON/.")
    else:
        latest_file = max(json_files, key=os.path.getctime)
        
        with open(latest_file, 'r', encoding='utf-8') as f:
            songs_data = json.load(f)
            
        if songs_data:
            top_song = songs_data[0]
            
            # Forcing a K-Pop test to prove the engine works!
            # Change this back to top_song['title'] after testing.
            test_title = "Khairiyat" 
            test_artist = "Arijit Singh"
            
            today_date = datetime.now().strftime("%Y-%m-%d")
            safe_title = re.sub(r'[\\/*?:"<>|]', "", test_title).strip()
            workspace_dir = os.path.join("Assets", f"{today_date}-{safe_title}")
            
            fetch_lyrics(test_title, test_artist, output_folder=workspace_dir)