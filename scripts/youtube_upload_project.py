from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
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
