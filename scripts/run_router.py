from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = sys.executable


def run(cmd: list[str]) -> int:
    env = dict(**__import__("os").environ)
    env.setdefault("PYTHONUTF8", "1")
    env.setdefault("PYTHONIOENCODING", "utf-8")
    src = str(ROOT / "src")
    env["PYTHONPATH"] = src + (";" + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    return subprocess.call(cmd, cwd=str(ROOT), env=env)


def print_extended_help() -> None:
    print("\nEchoForge extended commands:")
    print("  run.bat all [--project <project>] [--force-scrape] [--show-browser] [--no-popup] [--skip-editor-open]")
    print("  run.bat renderer prepare --project <project> [--force]")
    print("  run.bat renderer render --project <project>")
    print("  run.bat webeditor open --project <project>")
    print("  run.bat tubeharbor metadata --project <project> [--use-gemini|--no-gemini]")
    print("  run.bat tubeharbor upload --project <project> [--visibility private|public|unlisted] [--schedule-at ISO_TIME]")
    print("  run.bat tubeharbor mark-uploaded --project <project> [--video-id <id>] [--url <url>]")
    print("  run.bat project status --project <project>")
    print("  run.bat cleanup [--apply] [--remove-backups]")


def main() -> int:
    args = sys.argv[1:]
    if not args:
        code = run([PY, "-m", "echoforge"])
        print_extended_help()
        return code

    head = args[0].lower()

    if head == "all":
        return run([PY, "scripts/workflow_all.py", *args[1:]])

    if head == "renderer" and len(args) >= 2:
        sub = args[1].lower()
        rest = args[2:]
        if sub == "prepare":
            return run([PY, "scripts/prepare_editor_project.py", *rest])
        if sub == "render":
            return run([PY, "scripts/render_project.py", *rest])

    if head == "webeditor" and len(args) >= 2:
        sub = args[1].lower()
        rest = args[2:]
        if sub == "open":
            return run([PY, "scripts/open_webeditor.py", *rest])

    if head == "tubeharbor" and len(args) >= 2:
        sub = args[1].lower()
        rest = args[2:]
        if sub in {"metadata", "generate-metadata"}:
            return run([PY, "scripts/generate_youtube_metadata.py", *rest])
        if sub == "upload":
            return run([PY, "scripts/youtube_upload_project.py", *rest])
        if sub in {"mark-uploaded", "mark_used", "mark-used"}:
            return run([PY, "scripts/mark_project_uploaded.py", *rest])

    if head == "project" and len(args) >= 2 and args[1].lower() == "status":
        return run([PY, "scripts/project_status.py", *args[2:]])

    if head == "cleanup":
        return run([PY, "scripts/final_cleanup.py", *args[1:]])

    return run([PY, "-m", "echoforge", *args])


if __name__ == "__main__":
    raise SystemExit(main())
