from __future__ import annotations

from pathlib import Path


def find_project_root() -> Path:
    """Find the project root by searching upward for src/echoforge."""
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / "src" / "echoforge").is_dir():
            return parent
    return current.parents[2]


ROOT_DIR = find_project_root()

# Main project data directories
DATA_DIR = ROOT_DIR / "data"
PROJECTS_DIR = ROOT_DIR / "projects"
ASSETS_DIR = ROOT_DIR / "assets"
FONTS_DIR = ASSETS_DIR / "fonts"
BACKGROUNDS_DIR = ASSETS_DIR / "backgrounds"

# SongScout database & files
SONGSCOUT_DATA_DIR = DATA_DIR / "songscout"
SONGSCOUT_DB_PATH = SONGSCOUT_DATA_DIR / "songscout.sqlite3"
SONGSCOUT_RAW_JSON = SONGSCOUT_DATA_DIR / "youtube_charts_raw.json"
SONGSCOUT_CLEAN_JSON = SONGSCOUT_DATA_DIR / "youtube_charts_clean.json"

RUNTIME_DIRS = [
    DATA_DIR,
    SONGSCOUT_DATA_DIR,
    PROJECTS_DIR,
    ASSETS_DIR,
    FONTS_DIR,
    BACKGROUNDS_DIR,
]


def ensure_runtime_dirs() -> None:
    """Create runtime folders if they don't already exist."""
    for directory in RUNTIME_DIRS:
        directory.mkdir(parents=True, exist_ok=True)