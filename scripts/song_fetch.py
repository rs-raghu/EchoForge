"""
song_fetch.py

Downloads audio from YouTube as MP3 using yt-dlp.

CLI USAGE:
    python song_fetch.py --url "https://youtu.be/..." --output ./workspace
    python song_fetch.py --url "..." --output ./ws --filename track
"""

import argparse
import os

import yt_dlp

from config import AUDIO_FORMAT, AUDIO_BITRATE
from logger import get_logger
from utils import retry

log = get_logger(__name__)

# Sentinel returned when the video is geo/age-blocked or deleted.
UNAVAILABLE = "UNAVAILABLE"

_UNAVAILABLE_TRIGGERS = [
    "this video is not available",
    "video unavailable",
    "this video has been removed",
    "private video",
    "this video is private",
    "age-restricted",
    "sign in to confirm your age",
    "blocked in your country",
    "not available in your country",
]


def _is_retryable_download(exc: Exception) -> bool:
    """
    Returns False for permanent yt_dlp errors (geo-block, removed, private).
    All other errors (connection reset, timeout, HTTP 5xx) return True.
    """
    if isinstance(exc, yt_dlp.utils.DownloadError):
        msg = str(exc).lower()
        if any(trigger in msg for trigger in _UNAVAILABLE_TRIGGERS):
            return False
    return True


@retry(
    max_attempts=3,
    delay=10,
    backoff=2,
    exceptions=(Exception,),
    is_retryable=_is_retryable_download,
)
def _do_download(ydl_opts: dict, youtube_url: str) -> None:
    """
    Raw yt_dlp download. Decorated with @retry for transient network errors.
    Permanent failures bypass retry via the is_retryable guard.
    """
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([youtube_url])


def download_audio(youtube_url: str, output_folder: str, filename: str = "audio"):
    """
    Download the highest-quality audio stream as MP3.

    Returns:
      - Absolute path to the saved .mp3 on success.
      - UNAVAILABLE sentinel if the video is geo/age-blocked or removed.
      - None on other failures (after all retries exhausted).
    """
    log.info("🎵 Downloading audio: %s", youtube_url)

    ydl_opts = {
        "format": AUDIO_FORMAT,
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": AUDIO_BITRATE,
            }
        ],
        "outtmpl":           os.path.join(output_folder, f"{filename}.%(ext)s"),
        "quiet":             False,
        "no_warnings":       True,
        "nocheckcertificate": True,
    }

    try:
        _do_download(ydl_opts, youtube_url)

        final_path = os.path.join(output_folder, f"{filename}.mp3")
        if os.path.exists(final_path):
            log.info("✅ Audio saved: %s", final_path)
            return final_path

        log.error("❌ Audio file missing after download.")
        return None

    except yt_dlp.utils.DownloadError as exc:
        if any(t in str(exc).lower() for t in _UNAVAILABLE_TRIGGERS):
            log.error("⛔ Video unavailable: %s", youtube_url)
            return UNAVAILABLE
        log.error("❌ Download failed after all retries: %s", exc)
        return None

    except Exception as exc:
        log.error("❌ Download failed: %s", exc)
        return None


# ─── CLI ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="EchoForge Audio Downloader")
    parser.add_argument("--url",      required=True, help="YouTube URL to download")
    parser.add_argument("--output",   required=True, help="Output directory for the MP3")
    parser.add_argument("--filename", default="audio", help="Output filename without extension (default: audio)")
    args = parser.parse_args()

    os.makedirs(args.output, exist_ok=True)
    result = download_audio(args.url, args.output, args.filename)

    if result == UNAVAILABLE:
        print(f"\n⛔ UNAVAILABLE: video is geo/age-blocked or removed.")
    elif result:
        print(f"\n✅ Saved: {result}")
    else:
        print(f"\n❌ Download failed. Check the logs for details.")