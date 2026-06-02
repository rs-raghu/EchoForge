"""
engine/workers/youtube_upload.py

Uploads final_video.mp4 to YouTube using the Data API v3.

Bug 2 fix — sys.exit(0/1) instead of return True/False.

FIRST-RUN AUTH:
    Run this script directly once to generate token.json:
        python youtube_upload.py --auth-only

CLI USAGE:
    python youtube_upload.py --workspace ./workspaces/abc123 \\
                             --title "Song" --artist "Artist"
"""

import argparse
import os
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[3]
sys.path.append(str(ROOT_DIR))

from echoforge.utils.logger import get_logger

log = get_logger(__name__)

try:
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError
    from googleapiclient.http import MediaFileUpload
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
except ImportError:
    log.error("❌ Google API libraries missing. Run: pip install google-api-python-client google-auth-oauthlib google-auth-httplib2")
    build = None

CLIENT_SECRETS = str(ROOT_DIR / "client_secrets.json")
TOKEN_FILE     = str(ROOT_DIR / "database" / "token.json")
SCOPES         = ["https://www.googleapis.com/auth/youtube.upload"]


# ─── Auth ─────────────────────────────────────────────────────────────────────

def get_authenticated_service():
    """Load or refresh OAuth2 credentials and return the YouTube service."""
    creds = None

    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            log.info("🔄 Refreshing YouTube token...")
            try:
                creds.refresh(Request())
            except Exception as exc:
                log.error("❌ Token refresh failed: %s", exc)
                creds = None

        if not creds:
            if not os.path.exists(CLIENT_SECRETS):
                log.error("❌ client_secrets.json not found at %s", CLIENT_SECRETS)
                return None

            if sys.stdin.isatty():
                # Interactive — open browser
                flow  = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRETS, SCOPES)
                creds = flow.run_local_server(port=0)
            else:
                log.error(
                    "❌ Cannot perform OAuth login in a non-interactive process.\n"
                    "   Run:  python engine/workers/youtube_upload.py --auth-only"
                )
                return None

        os.makedirs(os.path.dirname(TOKEN_FILE), exist_ok=True)
        with open(TOKEN_FILE, "w") as fh:
            fh.write(creds.to_json())
        log.info("✅ Token saved: %s", TOKEN_FILE)

    return build("youtube", "v3", credentials=creds, cache_discovery=False)


# ─── Upload ───────────────────────────────────────────────────────────────────

def upload(song: dict) -> bool:
    """
    Upload final_video.mp4 to YouTube.
    Returns True on success, False on any failure.
    """
    if not build:
        return False

    workspace_dir = song.get("workspace_dir")
    title         = song.get("title", "Unknown")
    artist        = song.get("artist", "Unknown")

    if not workspace_dir:
        log.error("❌ Missing workspace_dir.")
        return False

    video_path = os.path.join(workspace_dir, "final_video.mp4")
    if not os.path.exists(video_path):
        log.error("❌ final_video.mp4 not found at %s", video_path)
        return False

    youtube = get_authenticated_service()
    if not youtube:
        return False

    # Build metadata
    yt_title = f"{title} - {artist} (Lyric Video)"
    if len(yt_title) > 100:
        yt_title = yt_title[:97] + "..."

    # Use AI-generated description if saved in workspace
    desc_path = os.path.join(workspace_dir, "description.txt")
    if os.path.exists(desc_path):
        with open(desc_path, "r", encoding="utf-8") as fh:
            description = fh.read().strip()
        log.info("📝 Using saved description from description.txt")
    else:
        description = (
            f"🎵 Lyric video for {title} by {artist}.\n\n"
            f"Generated automatically by EchoForge.\n"
            f"#{artist.replace(' ', '')} #{title.replace(' ', '')} #lyrics #lyricvideo"
        )

    body = {
        "snippet": {
            "title":       yt_title,
            "description": description,
            "tags":        ["lyrics", "lyric video", artist, title, "music"],
            "categoryId":  "10",
        },
        "status": {
            "privacyStatus":           "private",   # safe default — change to public when ready
            "selfDeclaredMadeForKids": False,
        },
    }

    log.info("📡 Uploading '%s' to YouTube [%s]...", yt_title, body["status"]["privacyStatus"])

    try:
        media   = MediaFileUpload(video_path, chunksize=-1, resumable=True, mimetype="video/mp4")
        request = youtube.videos().insert(
            part=",".join(body.keys()), body=body, media_body=media
        )

        response = None
        while response is None:
            status, response = request.next_chunk()
            if status:
                log.info("⏳ Upload progress: %d%%", int(status.progress() * 100))

        yt_id  = response.get("id")
        yt_url = f"https://www.youtube.com/watch?v={yt_id}"
        log.info("🎉 Upload complete: %s", yt_url)

        # Save the URL for reference
        with open(os.path.join(workspace_dir, "published_url.txt"), "w") as fh:
            fh.write(yt_url)

        return True

    except HttpError as exc:
        log.error("❌ YouTube API error %s: %s", exc.status_code, exc.reason)
        if "quotaExceeded" in str(exc):
            log.error("⚠️  Daily API quota exceeded — try again tomorrow.")
        return False

    except Exception as exc:
        log.exception("❌ Unexpected upload error: %s", exc)
        return False


# ── CLI ────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="EchoForge YouTube Uploader")
    parser.add_argument("--workspace", default=None,  help="Workspace directory")
    parser.add_argument("--title",     default="Test", help="Song title")
    parser.add_argument("--artist",    default="Test Artist")
    parser.add_argument("--auth-only", action="store_true",
                        help="Only generate/refresh token.json, do not upload.")
    args = parser.parse_args()

    if args.auth_only:
        svc = get_authenticated_service()
        print("✅ Auth OK" if svc else "❌ Auth failed")
        sys.exit(0 if svc else 1)

    if not args.workspace:
        parser.error("--workspace is required unless --auth-only is set.")

    song = {
        "title":         args.title,
        "artist":        args.artist,
        "workspace_dir": args.workspace,
    }
    ok = upload(song)
    print(f"\n{'✅ Success' if ok else '❌ Failed'}")
    sys.exit(0 if ok else 1)
