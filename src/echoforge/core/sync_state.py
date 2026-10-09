"""Publish and verify canonical timing pairs; interrupted publication fails closed."""
from pathlib import Path
from echoforge.core.media import fingerprint
from echoforge.core.storage import atomic_json, atomic_text, file_lock, read_json


def publish_sync(project: Path, lrc: str, payload: dict):
    project = Path(project)
    sync = project / "sync"
    with file_lock(sync / "publish.lock"):
        pending = sync / "publication_pending.json"
        atomic_json(pending, {"status": "publishing"})
        atomic_text(sync / "final_synced_lyrics.lrc", lrc)
        atomic_json(sync / "final_synced_lyrics.json", payload)
        atomic_json(sync / "publication.json", {
            "lrc": fingerprint(sync / "final_synced_lyrics.lrc"),
            "json": fingerprint(sync / "final_synced_lyrics.json"),
        })
        pending.unlink()


def validate_sync_pair(project: Path):
    sync = Path(project) / "sync"
    with file_lock(sync / "publish.lock"):
        if (sync / "publication_pending.json").exists():
            raise ValueError("Timing publication was interrupted; retry synchronization or approve timings again")
        marker = read_json(sync / "publication.json", {})
        if marker:
            for kind in ("lrc", "json"):
                path = sync / f"final_synced_lyrics.{kind}"
                if not path.exists() or marker.get(kind) != fingerprint(path):
                    raise ValueError("Canonical timings changed outside a completed publication; approve timings again")
