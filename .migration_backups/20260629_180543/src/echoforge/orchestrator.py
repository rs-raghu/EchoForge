from echoforge.core.paths import (
    ROOT_DIR,
    ensure_runtime_dirs,
    get_path_report,
)
from echoforge.core.config import print_settings


WORKFLOW = [
    "1. SongScout  - scrape chart and select next unused song",
    "2. MuseVault  - collect audio, lyrics, thumbnail, background",
    "3. VerseLock  - clean and sync lyrics",
    "4. WebEditor  - open project for manual visual editing",
    "5. Renderer   - render final lyrics video and upload thumbnail",
    "6. TubeHarbor - prepare metadata and upload/schedule",
]


def init_project() -> None:
    ensure_runtime_dirs()
    print("EchoForge runtime folders are ready.")


def show_status() -> None:
    ensure_runtime_dirs()

    print("\nEchoForge Status")
    print("=" * 50)

    print_settings()

    print("\nPaths")
    print("-" * 50)
    for name, path in get_path_report().items():
        print(f"{name:16} {path}")

    print("\nWorkflow")
    print("-" * 50)
    for stage in WORKFLOW:
        print(stage)

    print()


def doctor() -> None:
    ensure_runtime_dirs()

    print("\nEchoForge Doctor")
    print("=" * 50)

    required_paths = [
        ROOT_DIR / "apps" / "webeditor",
        ROOT_DIR / "assets",
        ROOT_DIR / "data",
        ROOT_DIR / "projects",
        ROOT_DIR / "src" / "echoforge",
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


def run_all_placeholder() -> None:
    print("\nFull workflow is not connected yet.")
    print("Next step: migrate SongScout into the clean structure.")