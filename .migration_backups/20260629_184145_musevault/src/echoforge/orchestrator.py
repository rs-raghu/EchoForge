from __future__ import annotations

from echoforge.core.config import print_settings
from echoforge.core.paths import ROOT_DIR, ensure_runtime_dirs, get_path_report
from echoforge.core.project_builder import init_next_project
from echoforge.stages.songscout.cleaner import clean_rows
from echoforge.stages.songscout.database import init_database, record_scrape_result, upsert_songs, workflow_counts
from echoforge.stages.songscout.policy import empty_database_message, should_scrape_today
from echoforge.stages.songscout.scraper import delete_transient_debug_files, scrape_youtube_charts

WORKFLOW = [
    "1. SongScout       - scrape chart only on Friday and select next unused song",
    "2. ProjectBuilder  - create clean project folder/state files",
    "3. MuseVault       - collect audio, lyrics, thumbnail, background",
    "4. VerseLock       - clean and sync lyrics",
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

    required_paths = [
        ROOT_DIR / "apps" / "webeditor",
        ROOT_DIR / "assets",
        ROOT_DIR / "data",
        ROOT_DIR / "data" / "songscout",
        ROOT_DIR / "projects",
        ROOT_DIR / "src" / "echoforge",
        ROOT_DIR / "src" / "echoforge" / "core" / "project_builder.py",
        ROOT_DIR / "src" / "echoforge" / "stages" / "songscout" / "database.py",
        ROOT_DIR / "src" / "echoforge" / "stages" / "songscout" / "policy.py",
        ROOT_DIR / "docs",
        ROOT_DIR / "tests",
        ROOT_DIR / ".env.example",
        ROOT_DIR / "requirements.txt",
        ROOT_DIR / "pyproject.toml",
    ]

    errors = []

    for path in required_paths:
        if path.exists():
            print(f"[OK]      {path.relative_to(ROOT_DIR)}")
        else:
            print(f"[MISSING] {path.relative_to(ROOT_DIR)}")
            errors.append(path)

    print()

    if errors:
        print("Doctor result: project structure has missing files/folders.")
    else:
        print("Doctor result: clean structure looks good.")


def show_workflow() -> None:
    print("\nEchoForge Workflow")
    print("=" * 50)
    for stage in WORKFLOW:
        print(stage)
    print()


def _refresh_songscout_for_workflow() -> None:
    decision = should_scrape_today(force=False)
    print(f"SongScout scrape policy: {decision.reason}")

    if not decision.should_scrape:
        return

    raw_rows = scrape_youtube_charts(max_songs=100, headless=True)
    clean_songs = clean_rows(raw_rows)
    result = upsert_songs(clean_songs)
    record_scrape_result(success=True, row_count=len(raw_rows), clean_count=len(clean_songs), reason=decision.reason)
    delete_transient_debug_files()
    print(f"SongScout scrape completed: {result}")


def run_all_placeholder() -> None:
    """
    Current connected workflow checkpoint.

    It now applies the Friday-only scrape policy, then initializes the next project.
    MuseVault is intentionally not connected yet because we are migrating one stage at a time.
    """
    ensure_runtime_dirs()
    init_database()

    print("\nEchoForge workflow checkpoint")
    print("=" * 50)
    print("Stage 1: SongScout")

    _refresh_songscout_for_workflow()

    message = empty_database_message()
    if message:
        print(message)
        return

    print("\nStage 2: ProjectBuilder")
    result = init_next_project()

    if not result.get("ok"):
        print(result.get("reason") or "No available project could be initialized.")
        print("Use `run.bat project selected` to see songs already inside the workflow.")
        return

    song = result.get("song") or {}
    print("\nProject ready:")
    print(f"project_id: {result.get('project_id')}")
    print(f"project_dir: {result.get('project_dir')}")
    print(f"song: #{song.get('rank') or '-'} {song.get('title')} — {song.get('artist')}")
    print(f"created: {result.get('created')}")
    print(f"reused: {result.get('reused')}")
    print("\nNext stage not connected yet: MuseVault migration comes next.")
