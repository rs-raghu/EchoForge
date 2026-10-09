import sys
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    from echoforge.stages.songscout import database
    from echoforge.core import project_builder
    from echoforge.stages.songscout import refresh
    from echoforge.stages.renderer import render_jobs
    from echoforge.stages.tubeharbor import upload_db
    monkeypatch.setattr(database, "SONGSCOUT_DB_PATH", tmp_path / "data/songs.sqlite3")
    monkeypatch.setattr(project_builder, "PROJECTS_DIR", tmp_path / "projects")
    monkeypatch.setattr(project_builder, "APP_STATE_DIR", tmp_path / "data")
    monkeypatch.setattr(refresh, "SONGSCOUT_DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(render_jobs, "_JOBS_FILE", tmp_path / "data/jobs.json")
    monkeypatch.setattr(upload_db, "DB_PATH", tmp_path / "data/uploads.json")
    database.init_database()
    return tmp_path
