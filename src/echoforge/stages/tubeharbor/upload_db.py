from pathlib import Path
from echoforge.core.paths import ROOT_DIR
from echoforge.core.storage import read_json, atomic_json, file_lock

DB_PATH = ROOT_DIR / "data" / "upload_db.json"


def _load_db():
    data = read_json(DB_PATH, {})
    if not isinstance(data, dict):
        raise ValueError("Upload ledger is corrupt; refusing to risk a duplicate upload")
    return data


def _save_db(data):
    atomic_json(DB_PATH, data)


def get_upload(project_dir):
    with file_lock(DB_PATH.with_suffix('.lock')):
        return _load_db().get(str(Path(project_dir).resolve()))


def is_uploaded(project_dir):
    record = get_upload(project_dir)
    return bool(record and (record.get('video_id') or record.get('status') in {'uploading', 'uncertain'}))


def record_upload(project_dir, result_data):
    with file_lock(DB_PATH.with_suffix('.lock')):
        db = _load_db()
        db[str(Path(project_dir).resolve())] = result_data
        _save_db(db)
