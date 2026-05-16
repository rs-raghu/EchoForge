"""
engine/workers/fetch_audio.py

Downloads the best audio from YouTube and saves it as audio.mp3
in the song's workspace directory.

Bug 2 fix
─────────
The function now calls sys.exit(0) on success and sys.exit(1) on failure
instead of returning True/False. When run as a multiprocessing.Process,
a Python return value does NOT set the OS exit code — returning False
still exits with code 0, which the orchestrator misreads as success.

CLI USAGE:
    python fetch_audio.py --video-id dQw4w9WgXcQ --workspace ./workspaces/dQw4w9WgXcQ
"""

import argparse
import os
import sys

# Ensure root is on the path when running as a standalone script
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from utils.logger import get_logger

log = get_logger(__name__)

try:
    import yt_dlp
except ImportError:
    log.error("❌ 'yt-dlp' is not installed. Run: pip install yt-dlp")
    yt_dlp = None

# Error messages that indicate a permanent, non-retryable failure
_PERMANENT_ERRORS = (
    "video unavailable", "this video is unavailable",
    "private video", "this video is private",
    "has been removed", "age-restricted",
    "sign in to confirm your age",
    "blocked in your country", "not available in your country",
    "copyright", "this video contains content",
)


def download(song: dict) -> bool:
    """
    Download audio for *song* and save as audio.mp3 in workspace_dir.
    Returns True on success, False on any failure.

    NOTE: When called as a multiprocessing.Process target, the caller
    (_run_audio_fetch in orchestrator.py) wraps this in sys.exit(0/1).
    """
    if not yt_dlp:
        log.error("❌ yt-dlp missing — cannot download.")
        return False

    video_id      = song.get("video_id", "")
    title         = song.get("title", "Unknown")
    workspace_dir = song.get("workspace_dir")
    url           = song.get("url") or f"https://www.youtube.com/watch?v={video_id}"

    if not workspace_dir:
        log.error("❌ Missing workspace_dir for '%s'", title)
        return False

    os.makedirs(workspace_dir, exist_ok=True)
    output_path = os.path.join(workspace_dir, "audio.mp3")

    if os.path.exists(output_path):
        log.info("✅ audio.mp3 already exists — skipping download.")
        return True

    log.info("⬇️  Downloading audio for '%s' from %s", title, url)

    ydl_opts = {
        "format":        "bestaudio/best",
        "outtmpl":       os.path.join(workspace_dir, "audio.%(ext)s"),
        "postprocessors": [{
            "key":              "FFmpegExtractAudio",
            "preferredcodec":   "mp3",
            "preferredquality": "192",
        }],
        "quiet":             True,
        "no_warnings":       True,
        "nocheckcertificate": True,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])

        if os.path.exists(output_path):
            log.info("✅ Audio saved: %s", output_path)
            return True

        log.error("❌ yt-dlp finished but audio.mp3 is missing.")
        return False

    except yt_dlp.utils.DownloadError as exc:
        msg = str(exc).lower()
        if any(trigger in msg for trigger in _PERMANENT_ERRORS):
            log.error("⛔ Video permanently unavailable: %s", url)
        else:
            log.error("❌ Download error: %s", exc)
        return False

    except Exception as exc:
        log.exception("❌ Unexpected error downloading audio: %s", exc)
        return False


# ── CLI ────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="EchoForge Audio Downloader")
    parser.add_argument("--video-id",  required=True,  help="YouTube video ID")
    parser.add_argument("--workspace", required=True,  help="Workspace directory path")
    parser.add_argument("--title",     default="Test", help="Song title (for logging)")
    args = parser.parse_args()

    song = {
        "video_id":     args.video_id,
        "title":        args.title,
        "workspace_dir": args.workspace,
    }
    os.makedirs(args.workspace, exist_ok=True)
    ok = download(song)
    print(f"\n{'✅ Success' if ok else '❌ Failed'}: {args.workspace}/audio.mp3")
    sys.exit(0 if ok else 1)
