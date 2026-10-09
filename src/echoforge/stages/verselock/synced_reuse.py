from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from echoforge.core.media import fingerprint
from echoforge.core.storage import atomic_json
from echoforge.stages.verselock.lrc_parser import lines_to_lrc, parse_lrc_file


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def write_json(path: Path, payload: dict[str, Any]) -> None:
    atomic_json(path, payload)


def update_project_state(project_dir: Path, result: dict[str, Any]) -> None:
    state_path = project_dir / "project_state.json"
    state = read_json(state_path)
    if not state:
        return

    stages = state.setdefault("stages", {})
    if result.get("ok"):
        stages["verselock"] = "done"
        state["current_stage"] = "synced"
    else:
        stages["verselock"] = "needs_review"
        state["current_stage"] = "verselock"

    state.setdefault("stage_reports", {})["verselock"] = result
    state["updated_at"] = now_utc_iso()
    write_json(state_path, state)


def update_asset_manifest(project_dir: Path, result: dict[str, Any]) -> None:
    manifest_path = project_dir / "asset_manifest.json"
    manifest = read_json(manifest_path)
    manifest.setdefault("sync", {})
    manifest["sync"].update(
        {
            "mode": result.get("mode"),
            "final_lrc": result.get("output_lrc"),
            "final_json": result.get("output_json"),
            "line_count": result.get("line_count", 0),
            "updated_at": now_utc_iso(),
        }
    )
    write_json(manifest_path, manifest)


def mark_song_synced_if_possible(project_dir: Path) -> None:
    state = read_json(project_dir / "project_state.json")
    song_id = state.get("song_id") or state.get("song", {}).get("id")
    if not song_id:
        return
    try:
        from echoforge.stages.songscout.database import mark_song_status

        mark_song_status(song_id, "synced", project_dir=str(project_dir), note="VerseLock reused existing synced lyrics")
    except Exception:
        pass


def reuse_existing_synced_lyrics(project_dir: str | Path, *, force: bool = False) -> dict[str, Any]:
    project_dir = Path(project_dir)
    input_lrc = project_dir / "lyrics" / "synced_lyrics.lrc"
    sync_dir = project_dir / "sync"
    output_lrc = sync_dir / "final_synced_lyrics.lrc"
    output_json = sync_dir / "final_synced_lyrics.json"
    report_path = sync_dir / "sync_report.json"

    if not project_dir.exists():
        return {
            "ok": False,
            "mode": "invalid_project",
            "reason": f"Project folder not found: {project_dir}",
        }

    if not input_lrc.exists():
        result = {
            "ok": False,
            "mode": "needs_full_alignment",
            "reason": "No lyrics/synced_lyrics.lrc found. Full alignment is not migrated yet.",
            "project_dir": str(project_dir),
        }
        update_project_state(project_dir, result)
        update_asset_manifest(project_dir, result)
        write_json(report_path, result)
        return result

    sync_dir.mkdir(parents=True, exist_ok=True)
    lines = parse_lrc_file(input_lrc)
    if not lines:
        result = {
            "ok": False,
            "mode": "invalid_existing_synced_lyrics",
            "reason": "lyrics/synced_lyrics.lrc exists, but no valid timestamped lyric lines were parsed.",
            "input": str(input_lrc),
            "project_dir": str(project_dir),
        }
        update_project_state(project_dir, result)
        update_asset_manifest(project_dir, result)
        write_json(report_path, result)
        return result

    # Rebuild this inexpensive derivation rather than trusting stale or corrupt pairs.
    output_lrc.write_text(lines_to_lrc(lines), encoding="utf-8")
    payload = {
        "schema": "echoforge.final_synced_lyrics.v1",
        "input_sha256": fingerprint(input_lrc),
        "source": "musevault.lyrics.synced_lyrics.lrc",
        "created_at": now_utc_iso(),
        "project_dir": str(project_dir),
        "line_count": len(lines),
        "lines": [line.to_dict() for line in lines],
    }
    write_json(output_json, payload)

    result = {
        "ok": True,
        "mode": "reuse_existing_synced_lyrics",
        "reused_existing_outputs": False,
        "input": str(input_lrc),
        "output_lrc": str(output_lrc),
        "output_json": str(output_json),
        "line_count": len(lines),
        "project_dir": str(project_dir),
    }
    update_project_state(project_dir, result)
    update_asset_manifest(project_dir, result)
    mark_song_synced_if_possible(project_dir)
    write_json(report_path, result)
    return result
