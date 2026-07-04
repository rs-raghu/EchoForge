from pathlib import Path


def find_project_root() -> Path:
    current = Path(__file__).resolve()

    for parent in current.parents:
        if (parent / "pyproject.toml").exists() and (parent / "src" / "echoforge").exists():
            return parent

    raise RuntimeError("Could not locate EchoForge project root.")


ROOT_DIR = find_project_root()

APPS_DIR = ROOT_DIR / "apps"
ASSETS_DIR = ROOT_DIR / "assets"
DATA_DIR = ROOT_DIR / "data"
DOCS_DIR = ROOT_DIR / "docs"
PROJECTS_DIR = ROOT_DIR / "projects"
SCRIPTS_DIR = ROOT_DIR / "scripts"
SRC_DIR = ROOT_DIR / "src"
TESTS_DIR = ROOT_DIR / "tests"

BACKGROUNDS_DIR = ASSETS_DIR / "backgrounds"
FONTS_DIR = ASSETS_DIR / "fonts"
REFERENCES_DIR = ASSETS_DIR / "references"

SONGSCOUT_DATA_DIR = DATA_DIR / "songscout"
APP_STATE_DIR = DATA_DIR / "app_state"

WEBEDITOR_DIR = APPS_DIR / "webeditor"
WEBEDITOR_BACKEND_DIR = WEBEDITOR_DIR / "backend"
WEBEDITOR_FRONTEND_DIR = WEBEDITOR_DIR / "frontend"


RUNTIME_DIRS = [
    DATA_DIR,
    SONGSCOUT_DATA_DIR,
    APP_STATE_DIR,
    PROJECTS_DIR,
    ASSETS_DIR,
    BACKGROUNDS_DIR,
    FONTS_DIR,
    REFERENCES_DIR,
]


def ensure_runtime_dirs() -> None:
    for path in RUNTIME_DIRS:
        path.mkdir(parents=True, exist_ok=True)


def get_path_report() -> dict[str, str]:
    return {
        "root": str(ROOT_DIR),
        "apps": str(APPS_DIR),
        "assets": str(ASSETS_DIR),
        "data": str(DATA_DIR),
        "projects": str(PROJECTS_DIR),
        "songscout_data": str(SONGSCOUT_DATA_DIR),
        "webeditor": str(WEBEDITOR_DIR),
    }