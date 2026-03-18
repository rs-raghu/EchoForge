import os
import subprocess
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from utils import retry
from config import THUMBNAIL_TIMESTAMP, YOUTUBE_PRIVACY

# ─── Configuration ────────────────────────────────────────────────────────────
# youtube.force-ssl is required for thumbnails.set on top of youtube.upload
SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.force-ssl",
]
SCRIPT_DIR          = os.path.dirname(os.path.abspath(__file__))
CLIENT_SECRETS_FILE = os.path.join(SCRIPT_DIR, "client_secrets.json")
TOKEN_FILE          = os.path.join(SCRIPT_DIR, "token.json")


# ─── Auth ─────────────────────────────────────────────────────────────────────

def get_authenticated_service():
    """Handles OAuth2 login and returns the YouTube API service."""
    creds = None

    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            print("🔄 Refreshing expired YouTube token...")
            creds.refresh(Request())
        else:
            print("🔐 First time login! Opening browser to authenticate...")
            flow  = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRETS_FILE, SCOPES)
            creds = flow.run_local_server(port=0)

        with open(TOKEN_FILE, 'w') as token:
            token.write(creds.to_json())

    return build('youtube', 'v3', credentials=creds)


# ─── Thumbnail extraction ──────────────────────────────────────────────────────

def extract_thumbnail(video_path: str) -> str | None:
    """
    Grabs a single frame at THUMBNAIL_TIMESTAMP from the rendered MP4
    using ffmpeg and saves it as thumbnail.jpg next to the video.

    The 4-second mark is the details screen (title + artist + background),
    which makes a clean, informative thumbnail.

    Returns the path to thumbnail.jpg, or None if extraction failed.
    """
    thumb_path = os.path.splitext(video_path)[0] + "_thumbnail.jpg"

    print(f"🖼️  Extracting thumbnail at {THUMBNAIL_TIMESTAMP}...")

    try:
        result = subprocess.run(
            [
                "ffmpeg",
                "-y",                          # overwrite if exists
                "-ss", THUMBNAIL_TIMESTAMP,    # seek to 4 s
                "-i", video_path,              # input video
                "-frames:v", "1",              # grab exactly one frame
                "-q:v", "2",                   # high quality JPEG (1=best, 31=worst)
                thumb_path,
            ],
            capture_output=True,
            text=True,
        )

        if result.returncode != 0:
            print(f"❌ ffmpeg thumbnail extraction failed:\n{result.stderr}")
            return None

        print(f"✅ Thumbnail saved: {thumb_path}")
        return thumb_path

    except FileNotFoundError:
        print("❌ ffmpeg not found. Make sure it's installed and on your PATH.")
        return None
    except Exception as e:
        print(f"❌ Thumbnail extraction crashed: {e}")
        return None


# ─── Retry-wrapped network primitives ─────────────────────────────────────────

def _is_retryable_upload(exc: Exception) -> bool:
    """
    Returns False for permanent upload errors that retrying can never fix:
      - 400 Bad Request    — malformed metadata
      - 401 Unauthorized   — token is invalid, not just expired
      - 403 Forbidden      — quota exceeded or account suspended
      - 404 Not Found      — video ID doesn't exist (mid-upload resume mismatch)
    All other errors (connection reset, timeout, 500/503) return True.
    """
    msg = str(exc)
    permanent_codes = ["400", "401", "403", "404"]
    return not any(code in msg for code in permanent_codes)


def _is_retryable_thumbnail(exc: Exception) -> bool:
    """
    403 on thumbnails.set means the channel isn't phone-verified —
    a permanent state that retrying won't fix.
    """
    msg = str(exc).lower()
    return "forbidden" not in msg and "403" not in msg


@retry(max_attempts=3, delay=15, backoff=2,
       exceptions=(Exception,), is_retryable=_is_retryable_upload)
def _do_upload_chunks(request) -> dict:
    """
    Drives the resumable upload chunk loop to completion and returns
    the API response dict containing the video ID.

    Decorated with @retry so transient network errors mid-upload are
    retried automatically (up to 3 attempts, 15s / 30s backoff).
    Permanent errors (4xx) are not retried via is_retryable.

    Note: Google's resumable upload protocol is inherently retry-safe —
    each `next_chunk()` call resumes from where the last chunk ended,
    so retrying the entire loop after a transient failure does not
    re-send already-acknowledged data.
    """
    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            print(f"⏳ Uploading... {int(status.progress() * 100)}%")
    return response


@retry(max_attempts=3, delay=10, backoff=2,
       exceptions=(Exception,), is_retryable=_is_retryable_thumbnail)
def _do_thumbnail_set(youtube, yt_video_id: str, thumb_path: str) -> None:
    """
    Calls thumbnails().set() and raises on any failure.
    Decorated with @retry so transient network errors are retried.
    403 (unverified channel) is not retried via is_retryable.
    """
    youtube.thumbnails().set(
        videoId    = yt_video_id,
        media_body = MediaFileUpload(thumb_path, mimetype="image/jpeg"),
    ).execute()


# ─── Thumbnail upload ──────────────────────────────────────────────────────────

def upload_thumbnail(youtube, yt_video_id: str, thumb_path: str) -> bool:
    """
    Pushes thumbnail.jpg to the already-uploaded YouTube video.

    NOTE: Your YouTube channel must be verified (phone-verified) before
    the thumbnails.set API call will be accepted. Unverified channels get
    a 403 forbidden error — verify at https://www.youtube.com/verify.

    Returns True on success, False on failure (non-fatal — video is already up).
    """
    print(f"🖼️  Uploading thumbnail to video {yt_video_id}...")

    try:
        _do_thumbnail_set(youtube, yt_video_id, thumb_path)
        print(f"✅ Thumbnail uploaded successfully!")
        return True

    except Exception as e:
        error_str = str(e)
        if "forbidden" in error_str.lower() or "403" in error_str:
            print(
                "⚠️  Thumbnail upload blocked (403). Your channel needs to be verified.\n"
                "   Verify at: https://www.youtube.com/verify — then re-run."
            )
        else:
            print(f"⚠️  Thumbnail upload failed after all retries (non-fatal): {e}")
        return False


# ─── Main upload function ──────────────────────────────────────────────────────

def upload_video(video_path: str, song_data: dict) -> str | None:
    """
    Full upload pipeline:
      1. Authenticate with YouTube.
      2. Upload the MP4 with all metadata (retried on transient errors).
      3. Extract the 4-second frame as a thumbnail.
      4. Push the thumbnail to the video (retried on transient errors).

    Returns the YouTube video ID on success, None on failure.
    """
    youtube = get_authenticated_service()

    # ── Build metadata ─────────────────────────────────────────────────────────
    title = f"{song_data['title']} by {song_data['artist']} | Lyric Video"
    if len(title) > 100:
        title = title[:97] + "..."

    description = (
        f"🎵 {song_data['title']} - {song_data['artist']}\n\n"
        f"Original Audio: {song_data['url']}\n"
        f"Generated automatically by EchoForge."
    )

    body = {
        'snippet': {
            'title':       title,
            'description': description,
            'tags':        [song_data['artist'], song_data['title'], 'lyrics', 'lyric video', 'EchoForge'],
            'categoryId':  '10',   # Music
        },
        'status': {
            'privacyStatus':          YOUTUBE_PRIVACY,
            'selfDeclaredMadeForKids': False,
        },
    }

    # ── Upload video ───────────────────────────────────────────────────────────
    print(f"📤 Preparing to upload: {title}  [{YOUTUBE_PRIVACY}]")

    media   = MediaFileUpload(video_path, chunksize=-1, resumable=True, mimetype='video/mp4')
    request = youtube.videos().insert(
        part       = ','.join(body.keys()),
        body       = body,
        media_body = media,
    )

    # _do_upload_chunks drives the chunk loop with automatic retry on
    # transient network failures. It raises on permanent errors (4xx).
    response    = _do_upload_chunks(request)
    yt_video_id = response.get('id')
    print(f"✅ Upload Complete! Video ID: {yt_video_id}")
    print(f"🔗 https://youtu.be/{yt_video_id}")

    # ── Extract and upload thumbnail ───────────────────────────────────────────
    thumb_path = extract_thumbnail(video_path)
    if thumb_path:
        upload_thumbnail(youtube, yt_video_id, thumb_path)
    else:
        print("⚠️  Skipping thumbnail upload (extraction failed).")

    return yt_video_id