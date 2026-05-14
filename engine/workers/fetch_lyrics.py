import os
import sys
import re

# Ensure the root directory is in the Python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from utils.logger import get_logger

log = get_logger(__name__)

try:
    import syncedlyrics
except ImportError:
    log.error("❌ 'syncedlyrics' is not installed! Run: pip install syncedlyrics")
    syncedlyrics = None

def fetch(song):
    """
    Fetches lyrics for the given song.
    Prefers synced .lrc files. Falls back to plain text .txt files.
    
    Returns True on success, False if no lyrics were found.
    """
    if not syncedlyrics:
        log.error("syncedlyrics module is missing. Cannot fetch lyrics.")
        return False

    title = song.get('title', '').strip()
    artist = song.get('artist', '').strip()
    workspace_dir = song.get('workspace_dir')

    if not title or not workspace_dir:
        log.error("❌ Missing title or workspace directory for lyrics fetch.")
        return False

    lrc_path = os.path.join(workspace_dir, "lyrics.lrc")
    txt_path = os.path.join(workspace_dir, "lyrics.txt")

    # Check if lyrics were already fetched (or manually added via Telegram)
    if os.path.exists(lrc_path) or os.path.exists(txt_path):
        log.info("✅ Lyrics already exist in the workspace. Skipping fetch.")
        return True

    search_query = f"{title} {artist}"
    log.info(f"📝 Searching for lyrics: '{search_query}'...")

    try:
        # syncedlyrics searches multiple providers and prioritizes synced LRCs
        lyrics_content = syncedlyrics.search(search_query)
        
        if not lyrics_content:
            log.warning(f"⚠️ No lyrics found anywhere for '{search_query}'.")
            return False

        # Check if the fetched content actually has timestamps (e.g., [01:23.45])
        is_synced = bool(re.search(r'\[\d{2}:\d{2}\.\d{2,3}\]', lyrics_content))

        if is_synced:
            with open(lrc_path, "w", encoding="utf-8") as f:
                f.write(lyrics_content)
            log.info(f"✅ Found SYNCED lyrics! Saved to {lrc_path}")
        else:
            # Strip any weird formatting and save as plain text
            clean_text = "\n".join([line.strip() for line in lyrics_content.split('\n') if line.strip()])
            with open(txt_path, "w", encoding="utf-8") as f:
                f.write(clean_text)
            log.info(f"✅ Found PLAIN TEXT lyrics. Saved to {txt_path}")

        return True

    except Exception as e:
        log.exception(f"❌ Unexpected error fetching lyrics: {e}")
        return False

# --- Independent Testing ---
if __name__ == "__main__":
    print("Testing Fetch Lyrics Worker...")
    test_song = {
        "title": "Blinding Lights",
        "artist": "The Weeknd",
        "workspace_dir": "./test_workspace"
    }
    os.makedirs(test_song["workspace_dir"], exist_ok=True)
    success = fetch(test_song)
    print(f"Fetch Success: {success}")