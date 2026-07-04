from __future__ import annotations

from pathlib import Path
from typing import Any

from echoforge.stages.verselock.synced_reuse import reuse_existing_synced_lyrics


def run_verselock_sync(project: str | Path, *, force: bool = False) -> dict[str, Any]:
    return reuse_existing_synced_lyrics(project, force=force)
