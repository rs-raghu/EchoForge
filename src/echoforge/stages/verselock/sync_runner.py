from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

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


def _safe_copy(src: Path, dst: Path) -> None:
    if src.exists():
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)


def _backup_existing_final(project_dir: Path, label: str) -> dict[str, str] | None:
    sync_dir = project_dir / "sync"
    final_lrc = sync_dir / "final_synced_lyrics.lrc"
    final_json = sync_dir / "final_synced_lyrics.json"
    if not final_lrc.exists() and not final_json.exists():
        return None
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = sync_dir / "candidates" / "final_backups"
    backup_lrc = backup_dir / f"{stamp}_{label}_final_synced_lyrics.lrc"
    backup_json = backup_dir / f"{stamp}_{label}_final_synced_lyrics.json"
    _safe_copy(final_lrc, backup_lrc)
    _safe_copy(final_json, backup_json)
    return {"lrc": str(backup_lrc), "json": str(backup_json)}


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


def _normalize_audio_if_possible(project_dir: Path, force: bool = False) -> dict[str, Any] | None:
    try:
        from echoforge.stages.musevault.audio_normalizer import normalize_project_audio
    except Exception:
        return None
    return normalize_project_audio(project_dir, force=force)


def run_whisper_fallback_sync(
    project: str | Path,
    *,
    force: bool = False,
    model_size: str = "medium",
    compute_type: str = "int8",
    language: str | None = None,
    beam_size: int = 5,
    promote: bool = True,
) -> dict[str, Any]:
    """Fallback VerseLock sync using Whisper timing + official lyrics text.

    This is intentionally not pure text alignment. Whisper can mishear words in songs,
    but its word timestamps are useful. timestamp_transfer_sync places the clean
    lyrics.txt lines onto the Whisper timing skeleton.
    """
    project_dir = Path(project)
    sync_dir = project_dir / "sync"
    sync_dir.mkdir(parents=True, exist_ok=True)

    audio_normalization = _normalize_audio_if_possible(project_dir, force=False)
    if audio_normalization is not None and not audio_normalization.get("ok"):
        result = {
            "ok": False,
            "mode": "whisper_timestamp_transfer_sync",
            "reason": "Audio normalization failed before Whisper fallback.",
            "audio_normalization": audio_normalization,
            "project_dir": str(project_dir),
        }
        _write_json(sync_dir / "sync_report.json", result)
        _update_project_state(project_dir, result)
        _update_asset_manifest(project_dir, result)
        return result

    try:
        from echoforge.stages.verselock.whisper_advanced import run_advanced_whisper_probe
    except Exception as exc:
        result = {
            "ok": False,
            "mode": "whisper_timestamp_transfer_sync",
            "reason": f"Advanced Whisper module is unavailable: {exc}",
            "project_dir": str(project_dir),
        }
        _write_json(sync_dir / "sync_report.json", result)
        _update_project_state(project_dir, result)
        _update_asset_manifest(project_dir, result)
        return result

    try:
        from echoforge.stages.verselock.timestamp_transfer import timestamp_transfer_sync
    except Exception as exc:
        result = {
            "ok": False,
            "mode": "whisper_timestamp_transfer_sync",
            "reason": f"Timestamp transfer module is unavailable: {exc}",
            "project_dir": str(project_dir),
        }
        _write_json(sync_dir / "sync_report.json", result)
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
            "mode": "whisper_timestamp_transfer_sync",
            "reason": "Whisper advanced transcription failed.",
            "audio_normalization": audio_normalization,
            "whisper": whisper,
            "project_dir": str(project_dir),
        }
        _write_json(sync_dir / "sync_report.json", result)
        _update_project_state(project_dir, result)
        _update_asset_manifest(project_dir, result)
        return result

    previous_final_backup = _backup_existing_final(project_dir, "before_whisper_transfer") if promote else None

    transfer = timestamp_transfer_sync(
        project_dir,
        transcript_path=sync_dir / "whisper_advanced_transcript.json",
        lyrics_path=project_dir / "lyrics" / "lyrics.txt",
        force=True,
        promote=promote,
        use_segments=False,
    )

    ok = bool(transfer.get("ok") and transfer.get("promoted_to_final"))
    result = {
        "ok": ok,
        "mode": "whisper_timestamp_transfer_sync",
        "reason": transfer.get("reason") or (None if ok else "Generated timing candidate requires review and explicit promotion."),
        "output_lrc": transfer.get("output_lrc"),
        "output_json": transfer.get("output_json"),
        "line_count": transfer.get("lyrics_line_count") or transfer.get("line_count"),
        "line_count_ratio": transfer.get("line_count_ratio"),
        "average_text_similarity": transfer.get("average_text_similarity"),
        "snapped_by_similarity": transfer.get("snapped_by_similarity"),
        "promoted_to_final": transfer.get("promoted_to_final"),
        "previous_final_backup": previous_final_backup,
        "audio_normalization": audio_normalization,
        "whisper": whisper,
        "timestamp_transfer": transfer,
        "project_dir": str(project_dir),
        "note": "Fallback uses official lyrics text with Whisper word timestamps. Text similarity is diagnostic only; timing skeleton quality matters more.",
    }
    _write_json(sync_dir / "sync_report.json", result)
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
        if result.get("ok"):
            return result

    return run_whisper_fallback_sync(
        project_dir,
        force=force,
        model_size=model_size,
        compute_type=compute_type,
        language=language,
        beam_size=beam_size,
        promote=False,
    )
