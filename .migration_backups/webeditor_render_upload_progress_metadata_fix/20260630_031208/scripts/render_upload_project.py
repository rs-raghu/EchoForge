from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

ROOT_DIR = Path(__file__).resolve().parents[1]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def resolve_project(project: str) -> Path:
    p = Path(project)
    if not p.is_absolute():
        p = ROOT_DIR / p
    return p.resolve()


def read_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def write_status(project_dir: Path, **updates: Any) -> Dict[str, Any]:
    path = project_dir / "upload" / "render_upload_status.json"
    current: Dict[str, Any] = {}
    if path.exists():
        try:
            current = read_json(path)
        except Exception:
            current = {}
    current.update(updates)
    current["updated_at"] = now_iso()
    write_json(path, current)
    return current


def run_cmd(cmd: list[str], *, cwd: Path, project_dir: Path, stage: str) -> Dict[str, Any]:
    write_status(project_dir, running=True, stage=stage, command=cmd)
    proc = subprocess.run(
        cmd,
        cwd=str(cwd),
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
    )
    log_dir = project_dir / "upload" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = log_dir / f"{stamp}_{stage}.log"
    log_path.write_text(
        "COMMAND:\n" + " ".join(cmd) + "\n\nSTDOUT:\n" + proc.stdout + "\n\nSTDERR:\n" + proc.stderr,
        encoding="utf-8",
    )
    if proc.returncode != 0:
        raise RuntimeError(f"{stage} failed. See log: {log_path}\n{proc.stdout[-1000:]}\n{proc.stderr[-1000:]}")
    return {"ok": True, "stage": stage, "log": str(log_path), "stdout": proc.stdout}


def save_request_metadata(project_dir: Path, request_data: Dict[str, Any]) -> Path:
    upload_dir = project_dir / "upload"
    upload_dir.mkdir(parents=True, exist_ok=True)
    metadata = request_data.get("metadata")
    metadata_path = upload_dir / "youtube_metadata.json"
    if isinstance(metadata, dict) and metadata:
        wrapper = {
            "ok": True,
            "mode": "youtube_metadata_generation",
            "source": "webeditor_review",
            "metadata": metadata,
            "created_at": now_iso(),
            "note": "Metadata reviewed/edited in WebEditor Render & Upload modal.",
        }
        write_json(metadata_path, wrapper)
    elif not metadata_path.exists():
        run_cmd(
            [sys.executable, str(ROOT_DIR / "scripts" / "generate_youtube_metadata.py"), "--project", str(project_dir)],
            cwd=ROOT_DIR,
            project_dir=project_dir,
            stage="metadata_generation",
        )
    return metadata_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Render a project, then optionally upload it to YouTube.")
    parser.add_argument("--project", required=True)
    parser.add_argument("--request", default="")
    args = parser.parse_args()

    project_dir = resolve_project(args.project)
    request_path = Path(args.request) if args.request else project_dir / "upload" / "render_upload_request.json"
    if not request_path.is_absolute():
        request_path = ROOT_DIR / request_path

    request_data: Dict[str, Any] = {}
    if request_path.exists():
        request_data = read_json(request_path)

    job_id = request_data.get("job_id") or datetime.now().strftime("%Y%m%d_%H%M%S")
    write_status(
        project_dir,
        ok=None,
        running=True,
        job_id=job_id,
        stage="starting",
        started_at=now_iso(),
        request_path=str(request_path),
        error=None,
    )

    try:
        metadata_path = save_request_metadata(project_dir, request_data)

        write_status(project_dir, running=True, stage="rendering")
        run_cmd(
            [sys.executable, str(ROOT_DIR / "scripts" / "render_project.py"), "--project", str(project_dir)],
            cwd=ROOT_DIR,
            project_dir=project_dir,
            stage="rendering",
        )

        final_video = project_dir / "renders" / "final_video.mp4"
        if not final_video.exists():
            raise FileNotFoundError(f"Render finished but final_video.mp4 not found: {final_video}")

        upload_requested = bool(request_data.get("upload", True))
        upload_result: Optional[Dict[str, Any]] = None

        if upload_requested:
            write_status(project_dir, running=True, stage="uploading")
            visibility = str(request_data.get("visibility") or "private")
            schedule_at = str(request_data.get("schedule_at") or request_data.get("scheduleAt") or "")
            upload_cmd = [
                sys.executable,
                str(ROOT_DIR / "scripts" / "youtube_upload_project.py"),
                "--project",
                str(project_dir),
                "--video",
                str(final_video),
                "--metadata",
                str(metadata_path),
                "--visibility",
                visibility,
            ]
            if schedule_at:
                upload_cmd.extend(["--schedule-at", schedule_at])
            upload_cmd.extend(["--thumbnail", str(project_dir / "renders" / "upload_thumbnail.jpg")])
            run_cmd(upload_cmd, cwd=ROOT_DIR, project_dir=project_dir, stage="youtube_upload")
            report_path = project_dir / "upload" / "youtube_upload_report.json"
            upload_result = read_json(report_path) if report_path.exists() else None
        else:
            write_status(project_dir, running=True, stage="render_complete_upload_skipped")

        result = {
            "ok": True,
            "running": False,
            "job_id": job_id,
            "stage": "done",
            "project_dir": str(project_dir),
            "rendered_video": str(final_video),
            "metadata_path": str(metadata_path),
            "upload_requested": upload_requested,
            "upload": upload_result,
            "finished_at": now_iso(),
        }
        write_status(project_dir, **result)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0

    except Exception as exc:
        result = {
            "ok": False,
            "running": False,
            "job_id": job_id,
            "stage": "failed",
            "error": str(exc),
            "project_dir": str(project_dir),
            "finished_at": now_iso(),
        }
        write_status(project_dir, **result)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
