from __future__ import annotations
import subprocess
import sys
from echoforge.core.config import print_settings
from echoforge.core.paths import ROOT_DIR, ensure_runtime_dirs, get_path_report
from echoforge.stages.songscout.database import init_database, workflow_counts
from echoforge.stages.songscout.policy import should_scrape_today

WORKFLOW = [
    "1. SongScout       - scrape chart only on Friday and select next unused song",
    "2. ProjectBuilder  - create clean project folder/state files",
    "3. MuseVault       - review metadata and collect audio/lyrics/images",
    "4. VerseLock       - use existing synced lyrics or run full alignment",
    "5. WebEditor       - open project for manual visual editing",
    "6. Renderer        - render final lyrics video and upload thumbnail",
    "7. TubeHarbor      - prepare metadata and upload/schedule",
]


def init_project() -> None:
    ensure_runtime_dirs()
    init_database()
    print("EchoForge runtime folders are ready.")


def show_status() -> None:
    ensure_runtime_dirs()
    init_database()
    print("\nEchoForge Status")
    print("=" * 50)
    print_settings()

    print("\nPaths")
    print("-" * 50)
    for name, path in get_path_report().items():
        print(f"{name:16} {path}")

    print("\nSongScout")
    print("-" * 50)
    decision = should_scrape_today(force=False)
    print(f"Today: {decision.weekday}, {decision.today}")
    print(f"Scrape now: {decision.should_scrape}")
    print(f"Reason: {decision.reason}")
    print(f"Counts: {workflow_counts()}")

    print("\nWorkflow")
    print("-" * 50)
    for stage in WORKFLOW:
        print(stage)
    print()


def doctor() -> None:
    ensure_runtime_dirs()
    init_database()
    print("\nEchoForge Doctor")
    print("=" * 50)
    required = [
        ROOT_DIR / "apps" / "webeditor",
        ROOT_DIR / "assets",
        ROOT_DIR / "data",
        ROOT_DIR / "data" / "songscout",
        ROOT_DIR / "projects",
        ROOT_DIR / "src" / "echoforge",
        ROOT_DIR / "src" / "echoforge" / "core" / "project_builder.py",
        ROOT_DIR / "src" / "echoforge" / "stages" / "songscout" / "database.py",
        ROOT_DIR / "src" / "echoforge" / "stages" / "songscout" / "policy.py",
        ROOT_DIR / "src" / "echoforge" / "stages" / "musevault" / "asset_collector.py",
        ROOT_DIR / "src" / "echoforge" / "stages" / "musevault" / "metadata_review.py",
        ROOT_DIR / "src" / "echoforge" / "stages" / "verselock" / "sync_runner.py",
        ROOT_DIR / ".env.example",
        ROOT_DIR / "requirements.txt",
        ROOT_DIR / "pyproject.toml",
    ]
    missing = []
    for path in required:
        if path.exists():
            print(f"[OK]      {path.relative_to(ROOT_DIR)}")
        else:
            print(f"[MISSING] {path.relative_to(ROOT_DIR)}")
            missing.append(path)
    print()
    print("Doctor result: project structure has missing files/folders." if missing else "Doctor result: clean structure looks good.")


def show_workflow() -> None:
    print("\nEchoForge Workflow")
    print("=" * 50)
    for stage in WORKFLOW:
        print(stage)
    print()


def _refresh_songscout_for_workflow() -> None:
    from echoforge.stages.songscout.refresh import refresh_chart
    print(f"SongScout refresh: {refresh_chart()}")


def run_all_placeholder() -> None:
    ensure_runtime_dirs()
    init_database()
    print("\nEchoForge full workflow")
    print("=" * 50)
    script = ROOT_DIR / "scripts" / "workflow_all.py"
    if not script.exists():
        print(f"Workflow script not found at {script}")
        return
    subprocess.run([sys.executable, str(script)], check=True)
