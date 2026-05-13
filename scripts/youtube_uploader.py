"""
youtube_uploader.py

Uploads rendered MP4 videos and custom thumbnails to YouTube.

Changes from v1:
  - upload_video() now accepts an optional thumbnail_path argument.
    When provided, this path (from thumbnail_gen.py) is used instead of
    the ffmpeg frame-grab fallback.
  - Added argparse CLI for standalone testing.

CLI USAGE:
    python youtube_uploader.py --video path/to/video.mp4 \\
                               --metadata path/to/metadata.json \\
                               --thumbnail path/to/thumbnail.jpg
"""

import argparse
import json
import os
import subprocess
from typing import Optional

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

from config import THUMBNAIL_TIMESTAMP, YOUTUBE_PRIVACY
from logger import get_logger
from utils import retry

log = get_logger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.force-ssl",
]
SCRIPT_DIR          = os.path.dirname(os.path.abspath(__file__))
CLIENT_SECRETS_FILE = os.path.join(SCRIPT_DIR, "client_secrets.json")
TOKEN_FILE          = os.path.join(SCRIPT_DIR, "token.json")


# ─── Auth ─────────────────────────────────────────────────────────────────────

def get_authenticated_service():
    """Handle OAuth2 login and return the YouTube API service object."""
    creds = None
    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            log.info("🔄 Refreshing expired YouTube token...")
            creds.refresh(Request())
        else:
            log.info("🔐 First-time login — opening browser...")
            flow  = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRETS_FILE, SCOPES)
            creds = flow.run_local_server(port=0)

        with open(TOKEN_FILE, "w") as fh:
            fh.write(creds.to_json())

    return build("youtube", "v3", credentials=creds)


# ─── Thumbnail extraction (ffmpeg fallback) ───────────────────────────────────

def extract_thumbnail(video_path: str) -> Optional[str]:
    """
    Grab a single frame at THUMBNAIL_TIMESTAMP from the rendered MP4.
    Returns the path to thumbnail.jpg, or None if extraction failed.
    Used as a fallback when thumbnail_gen.py did not produce a file.
    """
    thumb_path = os.path.splitext(video_path)[0] + "_thumbnail.jpg"
    log.info("🖼️  Extracting frame thumbnail at %s...", THUMBNAIL_TIMESTAMP)
    try:
        result = subprocess.run(
            [
                "ffmpeg", "-y",
                "-ss", THUMBNAIL_TIMESTAMP,
                "-i", video_path,
                "-frames:v", "1",
                "-q:v", "2",
                thumb_path,
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            log.error("❌ ffmpeg thumbnail extraction failed:\n%s", result.stderr)
            return None
        log.info("✅ Frame thumbnail saved: %s", thumb_path)
        return thumb_path
    except FileNotFoundError:
        log.error("❌ ffmpeg not found on PATH.")
        return None
    except Exception as exc:
        log.error("❌ Thumbnail extraction crashed: %s", exc)
        return None


# ─── Retry-wrapped upload primitives ──────────────────────────────────────────

def _is_retryable_upload(exc: Exception) -> bool:
    msg            = str(exc)
    permanent_codes = ["400", "401", "403", "404"]
    return not any(code in msg for code in permanent_codes)


def _is_retryable_thumbnail(exc: Exception) -> bool:
    msg = str(exc).lower()
    return "forbidden" not in msg and "403" not in msg


@retry(max_attempts=3, delay=15, backoff=2,
       exceptions=(Exception,), is_retryable=_is_retryable_upload)
def _do_upload_chunks(request) -> dict:
    """Drive the resumable upload chunk loop to completion."""
    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            log.debug("⏳ Upload progress: %d%%", int(status.progress() * 100))
    return response


@retry(max_attempts=3, delay=10, backoff=2,
       exceptions=(Exception,), is_retryable=_is_retryable_thumbnail)
def _do_thumbnail_set(youtube, yt_video_id: str, thumb_path: str) -> None:
    youtube.thumbnails().set(
        videoId    = yt_video_id,
        media_body = MediaFileUpload(thumb_path, mimetype="image/jpeg"),
    ).execute()


def upload_thumbnail(youtube, yt_video_id: str, thumb_path: str) -> bool:
    """Push a thumbnail to an already-uploaded YouTube video."""
    log.info("🖼️  Uploading thumbnail to video %s...", yt_video_id)
    try:
        _do_thumbnail_set(youtube, yt_video_id, thumb_path)
        log.info("✅ Thumbnail uploaded successfully!")
        return True
    except Exception as exc:
        if "forbidden" in str(exc).lower() or "403" in str(exc):
            log.warning(
                "⚠️  Thumbnail blocked (403). Verify your channel at "
                "https://www.youtube.com/verify then retry."
            )
        else:
            log.warning("⚠️  Thumbnail upload failed (non-fatal): %s", exc)
        return False


# ─── Main upload function ──────────────────────────────────────────────────────

def upload_video(
    video_path:     str,
    song_data:      dict,
    thumbnail_path: Optional[str] = None,
) -> Optional[str]:
    """
    Full upload pipeline:
      1. Authenticate with YouTube.
      2. Upload the MP4 with all metadata (retried on transient errors).
      3. Determine thumbnail source:
           a. thumbnail_path from thumbnail_gen.py  (preferred — custom Pillow layout)
           b. ffmpeg frame extraction fallback
      4. Push thumbnail to the video.

    Returns the YouTube video ID on success, None on failure.

    Args:
        video_path     : Absolute path to the rendered .mp4 file.
        song_data      : Dict with keys: title, artist, url, video_id.
        thumbnail_path : Optional path to a pre-generated thumbnail.jpg from
                         thumbnail_gen.py. Falls back to ffmpeg extraction when None.
    """
    youtube = get_authenticated_service()

    # ── Build metadata ─────────────────────────────────────────────────────────
    title = f"{song_data['title']} by {song_data['artist']} | Lyric Video"
    if len(title) > 100:
        title = title[:97] + "..."

    description = (
        f"🎵 {song_data['title']} - {song_data['artist']}\n\n"
        f"Original: {song_data.get('url', '')}\n"
        "Generated by EchoForge."
    )

    body = {
        "snippet": {
            "title":       title,
            "description": description,
            "tags":        [
                song_data.get("artist", ""), song_data.get("title", ""),
                "lyrics", "lyric video", "EchoForge",
            ],
            "categoryId": "10",   # Music
        },
        "status": {
            "privacyStatus":           YOUTUBE_PRIVACY,
            "selfDeclaredMadeForKids": False,
        },
    }

    log.info("📤 Uploading: %s  [%s]", title, YOUTUBE_PRIVACY)
    media   = MediaFileUpload(video_path, chunksize=-1, resumable=True, mimetype="video/mp4")
    request = youtube.videos().insert(
        part=",".join(body.keys()),
        body=body,
        media_body=media,
    )

    response    = _do_upload_chunks(request)
    yt_video_id = response.get("id")
    log.info("✅ Upload complete! Video ID: %s", yt_video_id)
    log.info("🔗 https://youtu.be/%s", yt_video_id)

    # ── Thumbnail ──────────────────────────────────────────────────────────────
    thumb = thumbnail_path if (thumbnail_path and os.path.exists(thumbnail_path)) else None

    if not thumb:
        log.info("ℹ️  No pre-generated thumbnail — falling back to ffmpeg extraction.")
        thumb = extract_thumbnail(video_path)

    if thumb:
        upload_thumbnail(youtube, yt_video_id, thumb)
    else:
        log.warning("⚠️  Skipping thumbnail upload (no file available).")

    return yt_video_id


# ─── CLI ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="EchoForge YouTube Uploader")
    parser.add_argument("--video",     required=True, help="Path to the rendered .mp4")
    parser.add_argument("--metadata",  required=True, help="Path to metadata.json")
    parser.add_argument("--thumbnail", default=None,  help="Path to thumbnail.jpg (optional)")
    args = parser.parse_args()

    with open(args.metadata, "r", encoding="utf-8") as fh:
        song = json.load(fh)

    vid_id = upload_video(
        video_path=args.video,
        song_data=song,
        thumbnail_path=args.thumbnail,
    )

    if vid_id:
        print(f"\n✅ Uploaded: https://youtu.be/{vid_id}")
    else:
        print("\n❌ Upload failed — check the logs.")