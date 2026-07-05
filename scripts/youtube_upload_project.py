from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def metadata(project: Path) -> dict[str, Any]:
    obj = load_json(project / "upload" / "youtube_metadata.json")
    return obj.get("metadata") if isinstance(obj.get("metadata"), dict) else obj


def build_youtube():
    try:
        from googleapiclient.discovery import build
        from google_auth_oauthlib.flow import InstalledAppFlow
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request
    except Exception as exc:
        raise RuntimeError("Missing YouTube upload dependencies. Run: pip install google-api-python-client google-auth-oauthlib google-auth-httplib2") from exc

    secrets = ROOT / ".secrets"
    client_secret = secrets / "youtube_client_secret.json"
    token_path = secrets / "youtube_token.json"
    if not client_secret.exists():
        raise FileNotFoundError(f"Missing {client_secret}. Download OAuth desktop client JSON from Google Cloud Console.")

    creds = None
    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(str(client_secret), SCOPES)
            creds = flow.run_local_server(port=0)
        token_path.write_text(creds.to_json(), encoding="utf-8")
    return build("youtube", "v3", credentials=creds)


def upload_video(project: Path, args: argparse.Namespace) -> dict[str, Any]:
    from googleapiclient.http import MediaFileUpload

    meta = metadata(project)
    video = Path(args.video) if args.video else project / "renders" / "final_video.mp4"
    thumb = Path(args.thumbnail) if args.thumbnail else project / "renders" / "upload_thumbnail.jpg"
    if not video.is_absolute():
        video = ROOT / video
    if not thumb.is_absolute():
        thumb = ROOT / thumb
    if not video.exists():
        raise FileNotFoundError(f"Rendered video not found: {video}")

    visibility = args.visibility or args.privacy or "private"
    status: dict[str, Any] = {
        "privacyStatus": "private" if visibility == "schedule" else visibility,
        "selfDeclaredMadeForKids": bool(meta.get("made_for_kids", False)),
    }
    if visibility == "schedule":
        if not args.schedule_at:
            raise ValueError("--schedule-at is required when visibility=schedule")
        status["publishAt"] = args.schedule_at

    body = {
        "snippet": {
            "title": args.title or meta.get("title") or "Lyrics Video",
            "description": args.description or meta.get("description") or "",
            "tags": [t for t in (args.tags.split(",") if args.tags else meta.get("tags", [])) if str(t).strip()],
            "categoryId": str(args.category_id or meta.get("category_id") or "10"),
        },
        "status": status,
    }

    yt = build_youtube()
    media = MediaFileUpload(str(video), chunksize=8 * 1024 * 1024, resumable=True, mimetype="video/mp4")
    request = yt.videos().insert(part="snippet,status", body=body, media_body=media)
    response = None
    last_progress = 0
    while response is None:
        progress, response = request.next_chunk()
        if progress:
            pct = int(progress.progress() * 100)
            if pct != last_progress:
                last_progress = pct
                print(json.dumps({"stage": "uploading", "progress": pct}, ensure_ascii=False), flush=True)
    video_id = response.get("id", "")

    thumb_result = None
    if video_id and thumb.exists():
        try:
            thumb_media = MediaFileUpload(str(thumb), mimetype="image/jpeg")
            thumb_result = yt.thumbnails().set(videoId=video_id, media_body=thumb_media).execute()
        except Exception as exc:
            thumb_result = {"ok": False, "error": str(exc)}

    result = {
        "ok": True,
        "mode": "youtube_upload",
        "video_id": video_id,
        "url": f"https://www.youtube.com/watch?v={video_id}" if video_id else "",
        "visibility": visibility,
        "schedule_at": args.schedule_at or "",
        "video": str(video),
        "thumbnail": str(thumb) if thumb.exists() else "",
        "thumbnail_result": thumb_result,
        "uploaded_at": datetime.now(timezone.utc).isoformat(),
        "metadata": body,
    }
    save_json(project / "upload" / "youtube_upload_report.json", result)
    return result


def main() -> int:
    ap = argparse.ArgumentParser(description="Upload rendered project to YouTube.")
    ap.add_argument("--project", required=True)
    ap.add_argument("--video", default="")
    ap.add_argument("--thumbnail", default="")
    ap.add_argument("--visibility", choices=["private", "public", "unlisted", "schedule"], default="private")
    ap.add_argument("--privacy", choices=["private", "public", "unlisted", "schedule"], default=None)
    ap.add_argument("--schedule-at", default="")
    ap.add_argument("--title", default="")
    ap.add_argument("--description", default="")
    ap.add_argument("--tags", default="")
    ap.add_argument("--category-id", default="")
    args = ap.parse_args()

    project = Path(args.project)
    if not project.is_absolute():
        project = ROOT / project
    try:
        result = upload_video(project, args)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        # Mark project and SongScout as used after successful upload.
        import subprocess
        subprocess.call([sys.executable, "scripts/mark_project_uploaded.py", "--project", str(project), "--video-id", result.get("video_id", ""), "--url", result.get("url", "")], cwd=ROOT)
        return 0
    except Exception as exc:
        result = {"ok": False, "mode": "youtube_upload", "reason": str(exc)}
        save_json(project / "upload" / "youtube_upload_report.json", result)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
