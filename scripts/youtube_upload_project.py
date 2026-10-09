from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
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
    from echoforge.stages.tubeharbor.youtube_uploader import upload_to_youtube
    video = Path(args.video) if args.video else project / 'renders/final_video.mp4'
    options = {key: value for key, value in vars(args).items() if value not in ('', None)}
    options['visibility'] = args.visibility or args.privacy or 'private'
    return upload_to_youtube(video, project, options)


def main() -> int:
    ap = argparse.ArgumentParser(description="Upload rendered project to YouTube.")
    ap.add_argument("--project", required=True)
    ap.add_argument("--video", default="")
    ap.add_argument("--thumbnail", default="")
    ap.add_argument("--visibility", choices=["private", "public", "unlisted", "schedule"], default=None)
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
        return 0 if result.get("ok") else 1
    except Exception as exc:
        result = {"ok": False, "mode": "youtube_upload", "reason": str(exc)}
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
