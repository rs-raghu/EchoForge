import os
import sys
import json
from pathlib import Path

# Ensure the root directory is in the Python path
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(ROOT_DIR)

from utils.logger import get_logger

log = get_logger(__name__)

try:
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from google.auth.transport.requests import Request
    from googleapiclient.errors import HttpError
except ImportError:
    log.error("❌ Google API client libraries are missing! Run: pip install google-api-python-client google-auth-httplib2 google-auth-oauthlib")
    build = None

# We store the secrets in the root, and the token in the database folder
CLIENT_SECRETS_FILE = os.path.join(ROOT_DIR, "client_secrets.json")
TOKEN_FILE = os.path.join(ROOT_DIR, "database", "token.json")
SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]

def get_authenticated_service():
    """
    Handles Google OAuth2 authentication. 
    Loads an existing token or prompts the user if run interactively.
    """
    creds = None
    
    # The file token.json stores the user's access and refresh tokens.
    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
        
    # If there are no (valid) credentials available, let the user log in.
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            log.info("🔄 Refreshing expired Google API token...")
            try:
                creds.refresh(Request())
            except Exception as e:
                log.error(f"❌ Failed to refresh token. It may have been revoked: {e}")
                creds = None

        if not creds:
            if not os.path.exists(CLIENT_SECRETS_FILE):
                log.error(f"❌ Missing {CLIENT_SECRETS_FILE}. Please download it from Google Cloud Console.")
                return None
                
            log.warning("⚠️ No valid OAuth token found!")
            log.warning("👉 You MUST run this script manually in your terminal once to log in and generate the token.json file.")
            
            # Only attempt to open the browser if we are running the script directly (interactive mode)
            if __name__ == "__main__":
                flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRETS_FILE, SCOPES)
                creds = flow.run_local_server(port=0)
            else:
                log.error("❌ Cannot perform OAuth login in the background process. Aborting upload.")
                return None

        # Save the credentials for the next run
        os.makedirs(os.path.dirname(TOKEN_FILE), exist_ok=True)
        with open(TOKEN_FILE, "w") as token:
            token.write(creds.to_json())
            log.info(f"✅ Google API Token saved to {TOKEN_FILE}")

    return build("youtube", "v3", credentials=creds, cache_discovery=False)

def upload(song):
    """
    Uploads the final_video.mp4 to YouTube using the authenticated API.
    Returns True on success, False on failure.
    """
    if not build:
        return False

    workspace_dir = song.get('workspace_dir')
    title = song.get('title', 'Unknown Title')
    artist = song.get('artist', 'Unknown Artist')
    
    if not workspace_dir:
        log.error("❌ Missing workspace directory.")
        return False

    video_path = os.path.join(workspace_dir, "final_video.mp4")
    
    if not os.path.exists(video_path):
        log.error(f"❌ Cannot upload! Video file not found at {video_path}")
        return False

    log.info(f"🚀 Preparing YouTube upload for '{title} by {artist}'...")

    youtube = get_authenticated_service()
    if not youtube:
        log.error("❌ Failed to authenticate with YouTube API.")
        return False

    # --- Video Metadata ---
    # You can customize this or pull a description from Claude/OpenAI if you saved it in the DB!
    upload_title = f"{title} - {artist} (Lyric Video)"
    
    # Truncate title if it exceeds YouTube's 100 character limit
    if len(upload_title) > 100:
        upload_title = upload_title[:97] + "..."

    description = (
        f"🎵 Lyric video for {title} by {artist}.\n\n"
        f"Generated automatically by EchoForge.\n"
        f"#lyrics #lyricvideo #{artist.replace(' ', '')} #{title.replace(' ', '')}"
    )

    tags = ["lyrics", "lyric video", artist, title, "music", "pop", "trending"]

    body = {
        "snippet": {
            "title": upload_title,
            "description": description,
            "tags": tags,
            "categoryId": "10" # 10 = Music
        },
        "status": {
            "privacyStatus": "public", # Use "private" or "unlisted" for testing!
            "selfDeclaredMadeForKids": False
        }
    }

    log.info("📡 Connecting to YouTube and uploading video chunks...")

    try:
        # Create the media file upload object
        media = MediaFileUpload(video_path, chunksize=-1, resumable=True, mimetype="video/mp4")

        # Execute the API request
        request = youtube.videos().insert(
            part=",".join(body.keys()),
            body=body,
            media_body=media
        )

        response = request.execute()
        
        youtube_url = f"https://www.youtube.com/watch?v={response.get('id')}"
        log.info(f"🎉 SUCCESS! Video uploaded to YouTube: {youtube_url}")
        
        # Save the published URL back to the workspace for your records
        with open(os.path.join(workspace_dir, "published_url.txt"), "w") as f:
            f.write(youtube_url)
            
        return True

    except HttpError as e:
        log.error(f"❌ YouTube API HTTP Error: {e.status_code} - {e.reason}")
        if "quotaExceeded" in str(e):
             log.error("⚠️ You have exceeded your YouTube Data API daily quota limit!")
        return False
    except Exception as e:
        log.exception(f"❌ Unexpected error during upload: {e}")
        return False

# --- Independent Testing / Token Generation ---
if __name__ == "__main__":
    print("Testing YouTube Upload Worker / Initializing Token...")
    # Running this directly allows the OAuth browser window to open if the token is missing.
    youtube_service = get_authenticated_service()
    if youtube_service:
        print("✅ Authentication successful. Ready to upload in the background.")
        
        # Uncomment below to test an actual upload
        # test_song = {
        #     "title": "Test Upload",
        #     "artist": "EchoForge",
        #     "workspace_dir": "./test_workspace"
        # }
        # upload(test_song) 