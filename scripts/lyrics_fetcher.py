import os
import re
import json
import glob
from datetime import datetime
import lyricsgenius

# --- CONFIGURATION ---
GENIUS_ACCESS_TOKEN = "A3_0t0cObi9eLcPYkX7mAoSmiabeBrxYaF0n-n9P5hXcczXG3ncRWLio7Z4LiE9E" 
genius = lyricsgenius.Genius(GENIUS_ACCESS_TOKEN)

# Keep the terminal clean from Genius's default debug logs
genius.verbose = False 
genius.remove_dict = True 

def clean_lyrics_text(raw_lyrics):
    """
    Heuristic filter to clean the messy text returned by the Genius API.
    Removes headers, view counts, and weird prefixes.
    """
    # 1. Genius often returns the first line as "Song Title Lyrics[Verse 1]". 
    # This removes everything up to and including the word "Lyrics" on the first line.
    clean_text = re.sub(r'^.*Lyrics', '', raw_lyrics, count=1)
    
    # 2. Remove the view count noise at the very end (e.g., "12KEmbed", "1.2MEmbed" or just "Embed")
    clean_text = re.sub(r'\d*(\.\d+)?K?M?Embed$', '', clean_text)
    clean_text = re.sub(r'Embed$', '', clean_text)
    
    # 3. Remove all section headers like [Chorus], [Verse 1], [Outro]
    clean_text = re.sub(r'\[.*?\]', '', clean_text)
    
    # 4. Clean up the empty blank lines left behind by the deleted headers
    # This rebuilds the string keeping only lines that actually contain text
    clean_text = "\n".join([line.strip() for line in clean_text.splitlines() if line.strip()])
    
    return clean_text

def fetch_lyrics(title, artist, output_folder):
    """
    Searches Genius for the song, cleans the formatting, 
    and saves the official lyrics to a text file.
    """
    print(f"📝 Searching Genius for: '{title}' by {artist}...")
    
    try:
        # Search Genius using the Title and Artist
        song = genius.search_song(title, artist)
        
        if song and song.lyrics:
            print("✅ Official lyrics found! Cleaning formatting...")
            
            # Pass the raw lyrics through our custom cleaning function
            cleaned = clean_lyrics_text(song.lyrics)
            
            # Ensure the output folder exists (just in case)
            os.makedirs(output_folder, exist_ok=True)
            
            # Save the pristine lyrics to the folder
            lyrics_path = os.path.join(output_folder, "lyrics.txt")
            with open(lyrics_path, 'w', encoding='utf-8') as f:
                f.write(cleaned)
                
            print(f"💾 Saved clean lyrics to: {lyrics_path}")
            return lyrics_path
        else:
            print("❌ Lyrics not found on Genius.")
            return None
            
    except Exception as e:
        print(f"❌ Error communicating with Genius API: {e}")
        return None

if __name__ == "__main__":
    # ==========================================
    # STANDALONE TEST: Read Top Song & Fetch Lyrics
    # ==========================================
    print("🔍 Looking for the latest YouTube Charts JSON...")
    
    json_folder = os.path.join("Database", "JSON")
    
    # Use glob to find all .json files in our database directory
    json_files = glob.glob(os.path.join(json_folder, "*.json"))
    
    if not json_files:
        print("❌ No JSON files found in Database/JSON/. Run your yt_scrapper.py first!")
    else:
        # Find the most recently created JSON file
        latest_file = max(json_files, key=os.path.getctime)
        print(f"📄 Reading top song from: {latest_file}\n")
        
        # Open it and grab the #1 song
        with open(latest_file, 'r', encoding='utf-8') as f:
            songs_data = json.load(f)
            
        if songs_data:
            top_song = songs_data[0]
            test_title = top_song['title']
            test_artist = top_song['artist']
            
            # --- CREATE THE ASSETS FOLDER STRUCTURE ---
            today_date = datetime.now().strftime("%Y-%m-%d")
            # Strip illegal characters for folder creation
            safe_title = re.sub(r'[\\/*?:"<>|]', "", test_title).strip()
            
            folder_name = f"{today_date}-{safe_title}"
            workspace_dir = os.path.join("Assets", folder_name)
            
            # Fetch and save directly into the new workspace
            fetch_lyrics(test_title, test_artist, output_folder=workspace_dir)
        else:
            print("❌ The JSON file is empty.")