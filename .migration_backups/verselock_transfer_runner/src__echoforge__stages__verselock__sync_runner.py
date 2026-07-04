from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from echoforge.stages.verselock.lyrics_whisper_aligner import align_lyrics_to_whisper
from echoforge.stages.verselock.synced_reuse import reuse_existing_synced_lyrics


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def _update_project_state(project_dir: Path, result: dict[str, Any]) -> None:
    state_path = project_dir / "project_state.json"
    state = _read_json(state_path)
    if not state:
        return
    stages = state.setdefault("stages", {})
    stages["verselock"] = "done" if result.get("ok") else "needs_review"
    state["current_stage"] = "synced" if result.get("ok") else "verselock_needs_review"
    state.setdefault("stage_reports", {})["verselock"] = result
    state["updated_at"] = now_iso()
    _write_json(state_path, state)


def _update_asset_manifest(project_dir: Path, result: dict[str, Any]) -> None:
    manifest_path = project_dir / "asset_manifest.json"
    manifest = _read_json(manifest_path)
    manifest.setdefault("assets", {})
    manifest["assets"]["final_synced_lyrics"] = {
        "status": "ready" if result.get("ok") else "needs_review",
        "mode": result.get("mode"),
        "lrc_path": result.get("output_lrc"),
        "json_path": result.get("output_json"),
        "details": result,
    }
    manifest["updated_at"] = now_iso()
    _write_json(manifest_path, manifest)


def _mark_song(project_dir: Path, result: dict[str, Any]) -> None:
    if not result.get("ok"):
        return
    state = _read_json(project_dir / "project_state.json")
    song_id = state.get("song_id") or state.get("song", {}).get("id")
    if not song_id:
        return
    try:
        from echoforge.stages.songscout.database import mark_song_status
        mark_song_status(song_id, "synced", project_dir=str(project_dir), note=f"VerseLock {result.get('mode')}")
    except Exception:
        pass


def run_whisper_fallback_sync(
    project: str | Path,
    *,
    force: bool = False,
    model_size: str = "medium",
    compute_type: str = "int8",
    language: str | None = None,
    beam_size: int = 5,
) -> dict[str, Any]:
    project_dir = Path(project)
    try:
        from echoforge.stages.verselock.whisper_advanced import run_advanced_whisper_probe
    except Exception as exc:
        result = {
            "ok": False,
            "mode": "whisper_fallback_sync",
            "reason": f"Advanced Whisper module is unavailable: {exc}",
            "project_dir": str(project_dir),
        }
        _update_project_state(project_dir, result)
        _update_asset_manifest(project_dir, result)
        return result

    whisper = run_advanced_whisper_probe(
        project=project_dir,
        model_size=model_size,
        compute_type=compute_type,
        language=language,
        force=force,
        beam_size=beam_size,
        vad_filter=False,
    )
    if not whisper.get("ok"):
        result = {
            "ok": False,
            "mode": "whisper_fallback_sync",
            "reason": "Whisper advanced transcription failed.",
            "whisper": whisper,
            "project_dir": str(project_dir),
        }
        _write_json(project_dir / "sync" / "sync_report.json", result)
        _update_project_state(project_dir, result)
        _update_asset_manifest(project_dir, result)
        return result

    alignment = align_lyrics_to_whisper(project_dir, force=True)
    result = {
        "ok": bool(alignment.get("ok")),
        "mode": "whisper_fallback_sync",
        "reason": alignment.get("reason"),
        "promoted_to_final": alignment.get("promoted_to_final"),
        "output_lrc": alignment.get("output_lrc"),
        "output_json": alignment.get("output_json"),
        "line_count": alignment.get("line_count"),
        "average_confidence": alignment.get("average_confidence"),
        "matched_ratio": alignment.get("matched_ratio"),
        "low_confidence_count": alignment.get("low_confidence_count"),
        "source_match_report": alignment.get("source_match_report"),
        "whisper": whisper,
        "alignment": alignment,
        "project_dir": str(project_dir),
    }
    _write_json(project_dir / "sync" / "sync_report.json", result)
    _update_project_state(project_dir, result)
    _update_asset_manifest(project_dir, result)
    _mark_song(project_dir, result)
    return result


def run_verselock_sync(
    project: str | Path,
    *,
    force: bool = False,
    force_fallback: bool = False,
    model_size: str = "medium",
    compute_type: str = "int8",
    language: str | None = None,
    beam_size: int = 5,
) -> dict[str, Any]:
    project_dir = Path(project)
    existing_lrc = project_dir / "lyrics" / "synced_lyrics.lrc"
    if existing_lrc.exists() and not force_fallback:
        result = reuse_existing_synced_lyrics(project_dir, force=force)
        _update_project_state(project_dir, result)
        _update_asset_manifest(project_dir, result)
        _mark_song(project_dir, result)
        return result
    return run_whisper_fallback_sync(
        project_dir,
        force=force,
        model_size=model_size,
        compute_type=compute_type,
        language=language,
        beam_size=beam_size,
    )
