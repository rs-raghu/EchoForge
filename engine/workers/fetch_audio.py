import os
import sys

# Ensure the root directory is in the Python path (3 levels up: fetch_audio.py -> workers -> engine -> root)
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from utils.logger import get_logger

log = get_logger(__name__)

try:
    import yt_dlp
except ImportError:
    log.error("❌ 'yt-dlp' is not installed! Run: pip install yt-dlp")
    yt_dlp = None

def download(song):
    """
    Downloads the best audio quality from YouTube and converts it to MP3.
    Saves it as 'audio.mp3' in the song's workspace directory.
    
    Returns True on success, False on failure.
    """
    if not yt_dlp:
        log.error("yt-dlp is missing. Cannot download audio.")
        return False

    title = song.get('title', 'Unknown')
    video_id = song.get('video_id')
    workspace_dir = song.get('workspace_dir')
    
    # If url isn't explicitly defined, build it from the video_id
    url = song.get('url')
    if not url and video_id:
        url = f"https://www.youtube.com/watch?v={video_id}"
        
    if not url or not workspace_dir:
        log.error(f"❌ Missing URL or workspace directory for '{title}'")
        return False

    output_path = os.path.join(workspace_dir, "audio.mp3")
    
    # Check if the file was already downloaded (e.g., if we are resuming a paused job)
    if os.path.exists(output_path):
        log.info(f"✅ Audio already exists at {output_path}. Skipping download.")
        return True

    log.info(f"⬇️ Downloading audio for '{title}' from {url}...")

    # yt-dlp configuration to extract audio and convert to 192k mp3
    ydl_opts = {
        'format': 'bestaudio/best',
        'outtmpl': os.path.join(workspace_dir, 'audio.%(ext)s'),
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }],
        'quiet': True,
        'no_warnings': True,
        'nocheckcertificate': True,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
            
        if os.path.exists(output_path):
            log.info(f"✅ Successfully downloaded and converted audio to {output_path}")
            return True
        else:
            log.error(f"❌ yt-dlp finished but audio.mp3 is missing in the workspace.")
            return False

    except yt_dlp.utils.DownloadError as e:
        err_msg = str(e).lower()
        if "unavailable" in err_msg or "private" in err_msg or "copyright" in err_msg or "age-restricted" in err_msg:
            log.error(f"⛔ Video unavailable, blocked, or restricted: {e}")
            # Note: We return False here. The Process Manager will catch this and mark the song as FAILED.
        else:
            log.error(f"❌ yt-dlp download error: {e}")
        return False
        
    except Exception as e:
        log.exception(f"❌ Unexpected error downloading audio: {e}")
        return False

# --- Independent Testing ---
if __name__ == "__main__":
    print("Testing Fetch Audio Worker...")
    # A safe, public domain / stock audio track or well-known video (Rick Roll) for testing
    test_song = {
        "title": "Rick Roll",
        "video_id": "dQw4w9WgXcQ", 
        "workspace_dir": "./test_workspace"
    }
    os.makedirs(test_song["workspace_dir"], exist_ok=True)
    success = download(test_song)
    print(f"Download Success: {success}")