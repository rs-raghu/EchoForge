from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List


ROOT = Path(__file__).resolve().parents[1]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def rel(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except Exception:
        return str(path)


def project_dir_from_arg(project: str) -> Path:
    p = Path(project)
    if not p.is_absolute():
        p = ROOT / p
    return p.resolve()


def status_path(project_dir: Path) -> Path:
    return project_dir / "upload" / "render_upload_status.json"


def write_status(project_dir: Path, **updates: Any) -> Dict[str, Any]:
    path = status_path(project_dir)
    path.parent.mkdir(parents=True, exist_ok=True)

    current: Dict[str, Any] = {}
    if path.exists():
        try:
            current = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            current = {}

    current.update(updates)
    current["updated_at"] = utc_now()
    current.setdefault("project_dir", rel(project_dir))
    path.write_text(json.dumps(current, indent=2, ensure_ascii=False), encoding="utf-8")
    return current


def run_cmd(project_dir: Path, args: List[str], step_name: str) -> Dict[str, Any]:
    env = os.environ.copy()
    env.setdefault("PYTHONUTF8", "1")
    env.setdefault("PYTHONIOENCODING", "utf-8")

    proc = subprocess.run(
        args,
        cwd=str(ROOT),
        env=env,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
    )

    return {
        "ok": proc.returncode == 0,
        "step": step_name,
        "returncode": proc.returncode,
        "stdout": proc.stdout[-8000:],
        "stderr": proc.stderr[-8000:],
    }


def parse_json_from_stdout(text: str) -> Dict[str, Any]:
    text = (text or "").strip()
    if not text:
        return {}
    try:
        return json.loads(text)
    except Exception:
        pass

    # Try to recover if something printed before JSON.
    first = text.find("{")
    last = text.rfind("}")
    if first >= 0 and last > first:
        try:
            return json.loads(text[first:last + 1])
        except Exception:
            return {}
    return {}


def load_metadata(project_dir: Path) -> Dict[str, Any]:
    path = project_dir / "upload" / "youtube_metadata.json"
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload.get("metadata") or payload
    except Exception:
        return {}


def generate_metadata(project_dir: Path, use_gemini: bool = True) -> Dict[str, Any]:
    cmd = [
        sys.executable,
        str(ROOT / "scripts" / "generate_youtube_metadata.py"),
        "--project",
        rel(project_dir),
    ]
    if use_gemini:
        cmd.append("--use-gemini")

    write_status(
        project_dir,
        ok=None,
        running=True,
        phase="metadata",
        progress=8,
        message="Generating YouTube metadata with Gemini/template...",
    )
    result = run_cmd(project_dir, cmd, "metadata")

    parsed = parse_json_from_stdout(result.get("stdout", ""))
    metadata = (parsed.get("metadata") if isinstance(parsed, dict) else None) or load_metadata(project_dir)

    if not result["ok"] or not metadata:
        write_status(
            project_dir,
            ok=False,
            running=False,
            phase="metadata_failed",
            progress=8,
            message="Metadata generation failed.",
            error=result,
        )
        raise RuntimeError("metadata_generation_failed")

    # No review step: use what the generator produced.
    write_status(
        project_dir,
        ok=None,
        running=True,
        phase="metadata_ready",
        progress=18,
        message="Metadata ready.",
        metadata={
            "title": metadata.get("title", ""),
            "tags_count": len(metadata.get("tags") or []),
            "source": metadata.get("source", parsed.get("source") if isinstance(parsed, dict) else ""),
        },
    )
    return metadata


def render_video(project_dir: Path) -> Path:
    write_status(
        project_dir,
        ok=None,
        running=True,
        phase="rendering",
        progress=25,
        message="Rendering final video...",
    )
    cmd = [sys.executable, str(ROOT / "scripts" / "render_project.py"), "--project", rel(project_dir)]
    result = run_cmd(project_dir, cmd, "render")

    parsed = parse_json_from_stdout(result.get("stdout", ""))
    video = None
    for key in ("output", "output_video", "video", "final_video", "path"):
        if isinstance(parsed, dict) and parsed.get(key):
            video = parsed[key]
            break

    if video:
        video_path = Path(video)
        if not video_path.is_absolute():
            video_path = ROOT / video_path
    else:
        video_path = project_dir / "renders" / "final_video.mp4"

    if not result["ok"] or not video_path.exists():
        write_status(
            project_dir,
            ok=False,
            running=False,
            phase="render_failed",
            progress=40,
            message="Render failed.",
            error=result,
            expected_video=rel(video_path),
        )
        raise RuntimeError("render_failed")

    write_status(
        project_dir,
        ok=None,
        running=True,
        phase="rendered",
        progress=70,
        message="Render complete.",
        video_path=rel(video_path),
    )
    return video_path


def upload_video(project_dir: Path, visibility: str, schedule_time: str | None = None) -> Dict[str, Any]:
    write_status(
        project_dir,
        ok=None,
        running=True,
        phase="uploading",
        progress=78,
        message="Uploading to YouTube...",
    )

    cmd = [
        sys.executable,
        str(ROOT / "scripts" / "youtube_upload_project.py"),
        "--project",
        rel(project_dir),
        "--visibility",
        visibility,
    ]
    if schedule_time:
        cmd += ["--schedule-time", schedule_time]

    result = run_cmd(project_dir, cmd, "upload")
    parsed = parse_json_from_stdout(result.get("stdout", ""))

    report_path = project_dir / "upload" / "youtube_upload_report.json"
    report: Dict[str, Any] = {}
    if report_path.exists():
        try:
            report = json.loads(report_path.read_text(encoding="utf-8"))
        except Exception:
            report = {}
    if isinstance(parsed, dict):
        report = {**report, **parsed}

    ok = bool(result["ok"] and (report.get("ok", True) is not False))
    video_id = report.get("video_id") or report.get("id")
    url = report.get("url") or report.get("video_url")
    if video_id and not url:
        url = f"https://www.youtube.com/watch?v={video_id}"

    if not ok:
        write_status(
            project_dir,
            ok=False,
            running=False,
            phase="upload_failed",
            progress=85,
            message="Upload failed.",
            error=result,
            upload_report=report,
        )
        raise RuntimeError("upload_failed")

    write_status(
        project_dir,
        ok=True,
        running=False,
        phase="uploaded",
        progress=100,
        message="Upload complete.",
        video_id=video_id,
        video_url=url,
        upload_report=report,
        completed_at=utc_now(),
    )
    return report


def main() -> int:
    ap = argparse.ArgumentParser(description="Render EchoForge project and optionally upload it to YouTube.")
    ap.add_argument("--project", required=True)
    ap.add_argument("--upload", action="store_true")
    ap.add_argument("--no-upload", action="store_true")
    ap.add_argument("--visibility", default="private", choices=["private", "public", "unlisted", "schedule"])
    ap.add_argument("--schedule-time", default="")
    ap.add_argument("--use-gemini", action="store_true", default=True)
    ap.add_argument("--no-gemini", action="store_true")
    args = ap.parse_args()

    project_dir = project_dir_from_arg(args.project)
    upload_enabled = bool(args.upload and not args.no_upload)

    requested_visibility = args.visibility
    effective_visibility = "private" if requested_visibility == "schedule" else requested_visibility
    schedule_time = args.schedule_time.strip() or None

    write_status(
        project_dir,
        ok=None,
        running=True,
        phase="starting",
        progress=2,
        message="Starting render job...",
        upload_enabled=upload_enabled,
        requested_visibility=requested_visibility,
        effective_visibility=effective_visibility,
        schedule_time=schedule_time,
        started_at=utc_now(),
    )

    try:
        metadata = generate_metadata(project_dir, use_gemini=not args.no_gemini)
        video_path = render_video(project_dir)

        if upload_enabled:
            report = upload_video(project_dir, visibility=effective_visibility, schedule_time=schedule_time)
            final = {
                "ok": True,
                "mode": "render_upload",
                "uploaded": True,
                "video_path": rel(video_path),
                "youtube": report,
                "metadata_title": metadata.get("title"),
                "status_path": rel(status_path(project_dir)),
            }
        else:
            write_status(
                project_dir,
                ok=True,
                running=False,
                phase="render_complete",
                progress=100,
                message="Render complete. Upload was not requested.",
                video_path=rel(video_path),
                metadata_title=metadata.get("title"),
                completed_at=utc_now(),
            )
            final = {
                "ok": True,
                "mode": "render_only",
                "uploaded": False,
                "video_path": rel(video_path),
                "metadata_title": metadata.get("title"),
                "status_path": rel(status_path(project_dir)),
            }

        print(json.dumps(final, indent=2, ensure_ascii=False))
        return 0

    except Exception as exc:
        current = write_status(
            project_dir,
            ok=False,
            running=False,
            phase="failed",
            progress=0,
            message=str(exc),
            failed_at=utc_now(),
        )
        print(json.dumps({
            "ok": False,
            "mode": "render_upload",
            "reason": str(exc),
            "status": current,
        }, indent=2, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
