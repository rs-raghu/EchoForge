from __future__ import annotations

from typing import Any

from echoforge.stages.songscout.database import (
    get_all_songs,
    get_next_available_song,
    get_song,
    mark_song_status,
)


def get_next_song(include_failed: bool = False) -> dict[str, Any] | None:
    return get_next_available_song(include_failed=include_failed)


def get_song_by_id(song_id: str) -> dict[str, Any] | None:
    return get_song(song_id)


def list_songs(limit: int = 20, status: str | None = None) -> list[dict[str, Any]]:
    return get_all_songs(limit=limit, status=status)


def mark_song_selected(song_id: str, project_dir: str | None = None, note: str | None = None) -> dict[str, Any] | None:
    return mark_song_status(song_id, "selected", project_dir=project_dir, note=note)


def mark_song_assets_ready(song_id: str, project_dir: str | None = None, note: str | None = None) -> dict[str, Any] | None:
    return mark_song_status(song_id, "assets_ready", project_dir=project_dir, note=note)


def mark_song_synced(song_id: str, project_dir: str | None = None, note: str | None = None) -> dict[str, Any] | None:
    return mark_song_status(song_id, "synced", project_dir=project_dir, note=note)


def mark_song_rendered(song_id: str, project_dir: str | None = None, note: str | None = None) -> dict[str, Any] | None:
    return mark_song_status(song_id, "rendered", project_dir=project_dir, note=note)


def mark_song_uploaded(song_id: str, project_dir: str | None = None, note: str | None = None) -> dict[str, Any] | None:
    return mark_song_status(song_id, "uploaded", project_dir=project_dir, note=note)


def mark_song_used(song_id: str, project_dir: str | None = None, note: str | None = None) -> dict[str, Any] | None:
    return mark_song_status(song_id, "used", project_dir=project_dir, note=note)


def mark_song_skipped(song_id: str, note: str | None = "Skipped manually") -> dict[str, Any] | None:
    return mark_song_status(song_id, "skipped", note=note)


def mark_song_failed(song_id: str, note: str | None = None) -> dict[str, Any] | None:
    return mark_song_status(song_id, "failed", note=note)
