import json
from pathlib import Path
from echoforge.core.paths import ROOT_DIR

DB_PATH = ROOT_DIR / "data" / "upload_db.json"

def _load_db() -> dict:
    if not DB_PATH.exists():
        return {}
    try:
        return json.loads(DB_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}

def _save_db(data: dict):
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    DB_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

def is_uploaded(project_dir: str | Path) -> bool:
    db = _load_db()
    project_key = str(Path(project_dir).resolve())
    return project_key in db

def record_upload(project_dir: str | Path, result_data: dict):
    db = _load_db()
    project_key = str(Path(project_dir).resolve())
    db[project_key] = result_data
    _save_db(db)