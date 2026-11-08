from __future__ import annotations

from pathlib import Path

# Root directory of EchoForge project
ROOT_DIR = Path(__file__).resolve().parent

# Secrets & credentials directory
SECRETS_DIR = (
    (ROOT_DIR / ".secrets") if (ROOT_DIR / ".secrets").is_dir() else (ROOT_DIR.parent / ".secrets")
)
YOUTUBE_CLIENT_SECRET_PATH = SECRETS_DIR / "youtube_client_secret.json"
YOUTUBE_TOKEN_PATH = SECRETS_DIR / "youtube_token.json"
GEMINI_API_KEY_PATH = SECRETS_DIR / "gemini_api_key.txt"

# Main project data directories
DATA_DIR = ROOT_DIR / "data"
PROJECTS_DIR = ROOT_DIR / "projects"
ASSETS_DIR = ROOT_DIR / "assets"
FONTS_DIR = ASSETS_DIR / "fonts"
BACKGROUNDS_DIR = ASSETS_DIR / "backgrounds"
WEBEDITOR_DIR = ROOT_DIR / "webeditor"

# SongScout database & files (flat in data/)
SONGSCOUT_DATA_DIR = DATA_DIR
SONGSCOUT_DB_PATH = DATA_DIR / "songscout.sqlite3"
SONGSCOUT_RAW_JSON = DATA_DIR / "youtube_charts_raw.json"
SONGSCOUT_CLEAN_JSON = DATA_DIR / "youtube_charts_clean.json"

RUNTIME_DIRS = [
    DATA_DIR,
    PROJECTS_DIR,
    ASSETS_DIR,
    FONTS_DIR,
    BACKGROUNDS_DIR,
    WEBEDITOR_DIR,
]


def ensure_runtime_dirs() -> None:
    """Create runtime folders if they don't already exist."""
    for directory in RUNTIME_DIRS:
        directory.mkdir(parents=True, exist_ok=True)
