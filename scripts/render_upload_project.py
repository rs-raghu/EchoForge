from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PY = sys.executable


def env() -> dict[str, str]:
    out = os.environ.copy()
    out.setdefault("PYTHONUTF8", "1")
    out.setdefault("PYTHONIOENCODING", "utf-8")
    src = str(ROOT / "src")
    out["PYTHONPATH"] = src + (";" + out["PYTHONPATH"] if out.get("PYTHONPATH") else "")
    return out


def save(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def load(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def stamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def run(cmd: list[str], status_file: Path, stage: str, progress: int, message: str) -> subprocess.CompletedProcess[str]:
    status = load(status_file)
    status.update({"stage": stage, "progress": progress, "message": message, "updated_at": stamp()})
    save(status_file, status)
    p = subprocess.run(cmd, cwd=ROOT, env=env(), text=True, encoding="utf-8", errors="replace", stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    logs = status.get("logs", [])
    logs.append({"stage": stage, "cmd": cmd, "returncode": p.returncode, "output_tail": p.stdout[-4000:]})
    status["logs"] = logs[-8:]
    save(status_file, status)
    return p


def main() -> int:
    ap = argparse.ArgumentParser(description="Generate metadata, render, and optionally upload a project.")
    ap.add_argument("--project", required=True)
    ap.add_argument("--upload", action="store_true")
    ap.add_argument("--no-upload", action="store_true")
    ap.add_argument("--visibility", choices=["private", "public", "unlisted", "schedule"], default="private")
    ap.add_argument("--schedule-at", default="")
    ap.add_argument("--title", default="")
    ap.add_argument("--description", default="")
    ap.add_argument("--tags", default="")
    ap.add_argument("--category-id", default="")
    ap.add_argument("--force", action="store_true")
    args, unknown = ap.parse_known_args()

    project = Path(args.project)
    if not project.is_absolute():
        project = ROOT / project
    status_file = project / "upload" / "render_upload_status.json"
    lock_file = project / "upload" / ".render_upload.lock"

    if lock_file.exists() and not args.force:
        current = load(status_file)
        if current.get("stage") not in {"uploaded", "rendered", "failed", "cancelled"}:
            print(json.dumps({"ok": False, "reason": "render_upload_already_running", "status": current}, indent=2, ensure_ascii=False))
            return 2
    lock_file.parent.mkdir(parents=True, exist_ok=True)
    lock_file.write_text(stamp(), encoding="utf-8")

    status = {
        "ok": None,
        "stage": "starting",
        "progress": 1,
        "message": "Starting render/upload job...",
        "project_dir": str(project.relative_to(ROOT) if project.is_relative_to(ROOT) else project),
        "started_at": stamp(),
        "updated_at": stamp(),
        "upload_requested": bool(args.upload and not args.no_upload),
    }
    save(status_file, status)

    try:
        p = run([PY, "scripts/generate_youtube_metadata.py", "--project", str(project)], status_file, "metadata", 10, "Generating YouTube metadata...")
        if p.returncode != 0:
            raise RuntimeError("metadata_generation_failed\n" + p.stdout[-2000:])

        p = run([PY, "scripts/render_project.py", "--project", str(project)], status_file, "rendering", 35, "Rendering final video...")
        if p.returncode != 0:
            raise RuntimeError("render_failed\n" + p.stdout[-3000:])

        status = load(status_file)
        status.update({"stage": "rendered", "progress": 70, "message": "Render complete.", "video": str(project / "renders" / "final_video.mp4"), "updated_at": stamp()})
        save(status_file, status)

        upload = args.upload and not args.no_upload
        if upload:
            cmd = [PY, "scripts/youtube_upload_project.py", "--project", str(project), "--visibility", args.visibility]
            if args.schedule_at:
                cmd += ["--schedule-at", args.schedule_at]
            if args.title:
                cmd += ["--title", args.title]
            if args.description:
                cmd += ["--description", args.description]
            if args.tags:
                cmd += ["--tags", args.tags]
            if args.category_id:
                cmd += ["--category-id", args.category_id]
            p = run(cmd, status_file, "uploading", 78, "Uploading to YouTube...")
            if p.returncode != 0:
                raise RuntimeError("upload_failed\n" + p.stdout[-4000:])
            report = load(project / "upload" / "youtube_upload_report.json")
            status = load(status_file)
            status.update({"ok": True, "stage": "uploaded", "progress": 100, "message": "Upload complete.", "youtube": report, "youtube_url": report.get("url") or report.get("video_url") or "", "updated_at": stamp(), "finished_at": stamp()})
            save(status_file, status)
        else:
            status = load(status_file)
            status.update({"ok": True, "stage": "rendered", "progress": 100, "message": "Render complete. Upload not requested.", "updated_at": stamp(), "finished_at": stamp()})
            save(status_file, status)

        print(json.dumps(load(status_file), indent=2, ensure_ascii=False))
        return 0
    except Exception as exc:
        status = load(status_file)
        status.update({"ok": False, "stage": "failed", "progress": 100, "message": str(exc), "updated_at": stamp(), "finished_at": stamp()})
        save(status_file, status)
        print(json.dumps(status, indent=2, ensure_ascii=False))
        return 1
    finally:
        try:
            lock_file.unlink()
        except FileNotFoundError:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
