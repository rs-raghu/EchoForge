from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
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


def run(cmd: list[str], *, allow_fail: bool = False) -> str:
    print("\n>>> " + " ".join(cmd), flush=True)
    p = subprocess.run(cmd, cwd=ROOT, env=env(), text=True, encoding="utf-8", errors="replace", stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    print(p.stdout, end="", flush=True)
    if p.returncode != 0 and not allow_fail:
        raise SystemExit(p.returncode)
    return p.stdout


def parse_project_dir(text: str) -> str | None:
    # First try JSON objects in the output.
    for m in reversed(re.findall(r"\{[\s\S]*?\}", text)):
        try:
            obj = json.loads(m)
        except Exception:
            continue
        for key in ("project_dir", "path", "project"):
            value = obj.get(key)
            if isinstance(value, str) and "projects" in value.lower():
                return value
    # Fallback: locate a projects\\... path.
    m = re.search(r"projects[\\/][A-Za-z0-9_ .()\-&]+", text)
    return m.group(0) if m else None


def latest_project() -> str | None:
    projects = ROOT / "projects"
    if not projects.exists():
        return None
    dirs = [p for p in projects.iterdir() if p.is_dir() and (p / "project_state.json").exists()]
    if not dirs:
        return None
    dirs.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return str(dirs[0].relative_to(ROOT))


def main() -> int:
    ap = argparse.ArgumentParser(description="Run EchoForge up to the WebEditor checkpoint.")
    ap.add_argument("--project", help="Existing project folder to continue instead of creating the next one.")
    ap.add_argument("--force-scrape", action="store_true", help="Force SongScout scrape before selecting.")
    ap.add_argument("--show-browser", action="store_true", help="Show browser during chart scrape.")
    ap.add_argument("--skip-scrape", action="store_true")
    ap.add_argument("--skip-musevault", action="store_true")
    ap.add_argument("--skip-verselock", action="store_true")
    ap.add_argument("--skip-editor-open", action="store_true")
    ap.add_argument("--no-popup", action="store_true", help="Disable MuseVault review popup.")
    ap.add_argument("--force-review", action="store_true")
    args = ap.parse_args()

    print("EchoForge full checkpoint workflow")
    print("Stops at WebEditor. Rendering/uploading stays controlled by the editor button.")

    project = args.project

    if not project:
        if not args.skip_scrape:
            scrape = [PY, "-m", "echoforge", "songscout", "scrape"]
            if args.force_scrape:
                scrape.append("--force")
            if args.show_browser:
                scrape.append("--show-browser")
            run(scrape, allow_fail=False)

        out = run([PY, "-m", "echoforge", "project", "init-next"])
        project = parse_project_dir(out) or latest_project()
        if not project:
            raise SystemExit("Could not determine created project path. Run run.bat project list and pass --project manually.")

    print(f"\nSelected project: {project}")

    if not args.skip_musevault:
        cmd = [PY, "-m", "echoforge", "musevault", "collect", "--project", project]
        if not args.no_popup:
            cmd.append("--popup")
        if args.force_review:
            cmd.append("--force-review")
        run(cmd)

    if not args.skip_verselock:
        run([PY, "-m", "echoforge", "verselock", "sync", "--project", project])

    run([PY, "scripts/prepare_editor_project.py", "--project", project, "--force"])
    run([PY, "scripts/project_status.py", "--project", project])

    if not args.skip_editor_open:
        return run([PY, "scripts/open_webeditor.py", "--project", project]) or 0

    print("\nEditor not opened because --skip-editor-open was used.")
    print(f"Open later with: run.bat webeditor open --project \"{project}\"")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
