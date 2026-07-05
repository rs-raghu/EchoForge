from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]


def read_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def resolve_project(project: str) -> Path:
    p = Path(project)
    if not p.is_absolute():
        p = ROOT_DIR / p
    return p.resolve()


def load_metadata(project_dir: Path, metadata_path: Optional[str] = None) -> Dict[str, Any]:
    path = Path(metadata_path) if metadata_path else project_dir / "upload" / "youtube_metadata.json"
    if not path.is_absolute():
        path = ROOT_DIR / path
    if not path.exists():
        raise FileNotFoundError(f"YouTube metadata file not found: {path}")
    data = read_json(path)
    return data.get("metadata", data)


def find_video(project_dir: Path, video_path: Optional[str] = None) -> Path:
    candidates = []
    if video_path:
        p = Path(video_path)
        candidates.append(p if p.is_absolute() else ROOT_DIR / p)
    candidates.extend([
        project_dir / "renders" / "final_video.mp4",
        project_dir / "renders" / "final.mp4",
    ])
    for p in candidates:
        if p.exists() and p.stat().st_size > 0:
            return p.resolve()
    raise FileNotFoundError("Rendered video not found. Expected renders/final_video.mp4")


def find_thumbnail(project_dir: Path, thumbnail_path: Optional[str] = None) -> Optional[Path]:
    candidates = []
    if thumbnail_path:
        p = Path(thumbnail_path)
        candidates.append(p if p.is_absolute() else ROOT_DIR / p)
    candidates.extend([
        project_dir / "renders" / "upload_thumbnail.jpg",
        project_dir / "renders" / "upload_thumbnail.png",
        project_dir / "images" / "music_thumbnail.jpg",
    ])
    for p in candidates:
        if p.exists() and p.stat().st_size > 0:
            return p.resolve()
    return None


def parse_schedule_at(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        dt = datetime.fromisoformat(text[:-1] + "+00:00")
    else:
        dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.now().astimezone().tzinfo)
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def re_split_tags(text: str) -> List[str]:
    import re
    parts = re.split(r"[,;\n]+", text)
    return [p.strip() for p in parts if p.strip()]


def normalize_tags(tags: Any, limit: int = 450) -> List[str]:
    if isinstance(tags, str):
        raw = re_split_tags(tags)
    elif isinstance(tags, list):
        raw = [str(x).strip() for x in tags if str(x).strip()]
    else:
        raw = []
    out: List[str] = []
    seen = set()
    total = 0
    for tag in raw:
        clean = tag.strip().lstrip("#").strip()
        if not clean:
            continue
        key = clean.lower()
        if key in seen:
            continue
        add_len = len(clean) + (1 if out else 0)
        if total + add_len > limit:
            break
        out.append(clean)
        seen.add(key)
        total += add_len
    if "winsomegin" not in {x.lower() for x in out}:
        out.insert(0, "winsomegin")
    return out


def get_credentials():
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
    except Exception as exc:
        raise RuntimeError(
            "Missing Google upload dependencies. Run: pip install google-api-python-client google-auth-oauthlib google-auth-httplib2"
        ) from exc

    secrets_dir = ROOT_DIR / ".secrets"
    client_secret = secrets_dir / "youtube_client_secret.json"
    token_path = secrets_dir / "youtube_token.json"

    if not client_secret.exists():
        raise FileNotFoundError(
            f"Missing YouTube OAuth client secret: {client_secret}. "
            "Create a Desktop OAuth client in Google Cloud and save it there."
        )

    creds = None
    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)

    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())

    if not creds or not creds.valid:
        flow = InstalledAppFlow.from_client_secrets_file(str(client_secret), SCOPES)
        creds = flow.run_local_server(port=0)

    secrets_dir.mkdir(parents=True, exist_ok=True)
    token_path.write_text(creds.to_json(), encoding="utf-8")
    return creds


def upload_video(
    project_dir: Path,
    *,
    video_path: Optional[str],
    metadata_path: Optional[str],
    visibility: str,
    schedule_at: Optional[str],
    thumbnail_path: Optional[str],
) -> Dict[str, Any]:
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload

    metadata = load_metadata(project_dir, metadata_path)
    video = find_video(project_dir, video_path)
    thumbnail = find_thumbnail(project_dir, thumbnail_path)

    title = str(metadata.get("title") or "Lyrics Video").strip()[:100]
    description = str(metadata.get("description") or "").strip()
    tags = normalize_tags(metadata.get("tags") or [])
    category_id = str(metadata.get("category_id") or metadata.get("categoryId") or "10")
    made_for_kids = bool(metadata.get("made_for_kids", False))

    visibility = (visibility or metadata.get("privacy_status") or "private").strip().lower()
    if visibility == "schedule":
        visibility = "private"

    status = {
        "privacyStatus": visibility if visibility in {"private", "public", "unlisted"} else "private",
        "selfDeclaredMadeForKids": made_for_kids,
    }

    publish_at = parse_schedule_at(schedule_at)
    if publish_at:
        status["privacyStatus"] = "private"
        status["publishAt"] = publish_at

    body = {
        "snippet": {
            "title": title,
            "description": description,
            "tags": tags,
            "categoryId": category_id,
        },
        "status": status,
    }

    creds = get_credentials()
    youtube = build("youtube", "v3", credentials=creds)

    media = MediaFileUpload(str(video), chunksize=8 * 1024 * 1024, resumable=True, mimetype="video/mp4")
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)

    response = None
    while response is None:
        status_obj, response = request.next_chunk()
        if status_obj:
            print(json.dumps({"stage": "uploading", "progress": int(status_obj.progress() * 100)}, ensure_ascii=False), flush=True)

    video_id = response.get("id")
    url = f"https://www.youtube.com/watch?v={video_id}" if video_id else ""

    thumb_response = None
    if video_id and thumbnail:
        try:
            thumb_media = MediaFileUpload(str(thumbnail), mimetype="image/jpeg")
            thumb_response = youtube.thumbnails().set(videoId=video_id, media_body=thumb_media).execute()
        except Exception as exc:
            thumb_response = {"ok": False, "error": str(exc)}

    report = {
        "ok": True,
        "mode": "youtube_upload",
        "video_id": video_id,
        "url": url,
        "visibility": body["status"].get("privacyStatus"),
        "publish_at": body["status"].get("publishAt"),
        "title": title,
        "tags": tags,
        "video_path": str(video),
        "thumbnail_path": str(thumbnail) if thumbnail else None,
        "thumbnail_response": thumb_response,
        "youtube_response": response,
    }
    write_json(project_dir / "upload" / "youtube_upload_report.json", report)

    state_path = project_dir / "project_state.json"
    if state_path.exists():
        try:
            state = read_json(state_path)
            state.setdefault("tubeharbor", {})
            state["tubeharbor"].update({
                "uploaded": True,
                "video_id": video_id,
                "url": url,
                "visibility": report["visibility"],
                "publish_at": report["publish_at"],
            })
            state["status"] = "uploaded"
            write_json(state_path, state)
        except Exception:
            pass

    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Upload a rendered EchoForge video to YouTube.")
    parser.add_argument("--project", required=True)
    parser.add_argument("--video")
    parser.add_argument("--metadata")
    parser.add_argument("--visibility", default="private", choices=["private", "public", "unlisted", "schedule"])
    parser.add_argument("--schedule-at", default="")
    parser.add_argument("--thumbnail", default="")
    args = parser.parse_args()

    project_dir = resolve_project(args.project)
    try:
        result = upload_video(
            project_dir,
            video_path=args.video,
            metadata_path=args.metadata,
            visibility=args.visibility,
            schedule_at=args.schedule_at,
            thumbnail_path=args.thumbnail,
        )
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0
    except Exception as exc:
        result = {
            "ok": False,
            "mode": "youtube_upload",
            "reason": str(exc),
            "project_dir": str(project_dir),
        }
        write_json(project_dir / "upload" / "youtube_upload_report.json", result)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
