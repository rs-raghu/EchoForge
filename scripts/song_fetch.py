import os
import yt_dlp
from utils import retry
from config import AUDIO_FORMAT, AUDIO_BITRATE

# Sentinel return value so master_controller can distinguish
# "video unavailable" from other failures and auto-skip
UNAVAILABLE = "UNAVAILABLE"

# Phrases that indicate a permanent, non-retryable failure.
# Geo-blocks, age gates, and removed videos will never succeed on retry.
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
    Those will never succeed on retry so we let them propagate immediately.
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
    Raw yt_dlp download — raises on any failure.
    Decorated with @retry so transient network errors are automatically
    retried (up to 3 attempts, 10s / 20s backoff).
    Permanent failures (geo-block, removed video) bypass retry immediately
    via the is_retryable guard and surface in download_audio() as usual.
    """
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([youtube_url])


def download_audio(youtube_url: str, output_folder: str, filename: str = "audio"):
    """
    Downloads the highest quality audio stream as MP3.
    Returns:
      - file path string on success
      - UNAVAILABLE sentinel if the video is geo/age restricted or deleted
      - None on other failures (after all retries exhausted)
    """
    print(f"🎵 Extracting audio from: {youtube_url}")

    ydl_opts = {
        'format': AUDIO_FORMAT,
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': AUDIO_BITRATE,
        }],
        'outtmpl': os.path.join(output_folder, f"{filename}.%(ext)s"),
        'quiet': False,
        'no_warnings': True,
        'nocheckcertificate': True,
    }

    try:
        _do_download(ydl_opts, youtube_url)

        final_path = os.path.join(output_folder, f"{filename}.mp3")
        if os.path.exists(final_path):
            print(f"✅ Audio successfully saved to: {final_path}")
            return final_path
        else:
            print(f"❌ Audio file not found after download.")
            return None

    except yt_dlp.utils.DownloadError as e:
        error_msg = str(e).lower()
        if any(trigger in error_msg for trigger in _UNAVAILABLE_TRIGGERS):
            print(f"⛔ Video unavailable (geo/age/removed): {youtube_url}")
            return UNAVAILABLE

        print(f"❌ Audio download failed after all retries: {e}")
        return None

    except Exception as e:
        print(f"❌ Audio download failed after all retries: {e}")
        return None