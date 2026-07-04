from __future__ import annotations

from echoforge.core.config import print_settings
from echoforge.core.paths import ROOT_DIR, ensure_runtime_dirs, get_path_report
from echoforge.stages.songscout.database import init_database, workflow_counts
from echoforge.stages.songscout.policy import empty_database_message, should_scrape_today
from echoforge.stages.songscout.selector import get_next_song
from echoforge.stages.songscout.cleaner import clean_rows
from echoforge.stages.songscout.database import record_scrape_result, upsert_songs
from echoforge.stages.songscout.scraper import delete_transient_debug_files, scrape_youtube_charts

WORKFLOW = [
    "1. SongScout  - scrape chart only on Friday and select next unused song",
    "2. MuseVault  - collect audio, lyrics, thumbnail, background",
    "3. VerseLock  - clean and sync lyrics",
    "4. WebEditor  - open project for manual visual editing",
    "5. Renderer   - render final lyrics video and upload thumbnail",
    "6. TubeHarbor - prepare metadata and upload/schedule",
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

    It now applies the Friday-only scrape policy, then selects the next song.
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

    song = get_next_song()
    if not song:
        print("No available new songs found. Use `run.bat songscout list --status used` or reset/skip statuses if needed.")
        return

    print("\nSelected next song:")
    print(f"#{song.get('rank') or '-'}  {song.get('title')} — {song.get('artist')}")
    print(f"id: {song.get('id')}")
    print("\nNext stage not connected yet: MuseVault migration comes after SongScout is approved.")
