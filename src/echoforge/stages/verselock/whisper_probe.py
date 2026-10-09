from __future__ import annotations

from echoforge.core.storage import atomic_text

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def seconds_to_lrc_timestamp(seconds: float) -> str:
    total_ms = max(int(round(seconds * 1000)), 0)
    minutes = total_ms // 60000
    remaining = total_ms % 60000
    secs = remaining // 1000
    hundredths = (remaining % 1000) // 10
    return f"{minutes:02d}:{secs:02d}.{hundredths:02d}"


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists(): return {}
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path, payload):
    from echoforge.core.storage import atomic_json
    atomic_json(path, payload)


def find_audio_file(project_dir: Path) -> Path | None:
    audio_dir = project_dir / "audio"
    preferred = [
        audio_dir / "source_audio.m4a",
        audio_dir / "source_audio.mp3",
        audio_dir / "source_audio.wav",
        audio_dir / "source_audio.webm",
        audio_dir / "source_audio.mp4",
    ]
    for item in preferred:
        if item.exists():
            return item
    if audio_dir.exists():
        for ext in ("*.m4a", "*.mp3", "*.wav", "*.webm", "*.mp4", "*.mkv", "*.aac", "*.flac"):
            found = sorted(audio_dir.glob(ext))
            if found:
                return found[0]
    return None


def _segments_to_payload(segments: list[dict[str, Any]], *, engine: str, model_size: str, audio_path: Path, language: str | None) -> dict[str, Any]:
    clean_segments = []
    for idx, segment in enumerate(segments):
        text = " ".join(str(segment.get("text", "")).split()).strip()
        if not text:
            continue
        start = float(segment.get("start", 0.0))
        end = float(segment.get("end", start))
        clean_segments.append(
            {
                "index": len(clean_segments),
                "start_seconds": round(start, 3),
                "end_seconds": round(end, 3),
                "start_ms": int(round(start * 1000)),
                "end_ms": int(round(end * 1000)),
                "timestamp": seconds_to_lrc_timestamp(start),
                "text": text,
            }
        )
    return {
        "schema": "echoforge.whisper_probe.v1",
        "created_at": now_utc_iso(),
        "engine": engine,
        "model_size": model_size,
        "language": language,
        "audio_path": str(audio_path),
        "segment_count": len(clean_segments),
        "segments": clean_segments,
    }


def _payload_to_lrc(payload: dict[str, Any]) -> str:
    lines = []
    for segment in payload.get("segments", []):
        text = str(segment.get("text", "")).strip()
        if text:
            lines.append(f"[{segment['timestamp']}] {text}")
    return "\n".join(lines).strip() + "\n"


def _run_faster_whisper(audio_path: Path, *, model_size: str, language: str | None, device: str, compute_type: str) -> tuple[dict[str, Any], dict[str, Any]]:
    from faster_whisper import WhisperModel

    model = WhisperModel(model_size, device=device, compute_type=compute_type)
    seg_iter, info = model.transcribe(
        str(audio_path),
        language=language,
        beam_size=5,
        vad_filter=True,
        word_timestamps=False,
    )
    raw_segments = []
    for seg in seg_iter:
        raw_segments.append({"start": float(seg.start), "end": float(seg.end), "text": seg.text})
    info_payload = {
        "detected_language": getattr(info, "language", None),
        "language_probability": getattr(info, "language_probability", None),
        "duration": getattr(info, "duration", None),
    }
    payload = _segments_to_payload(raw_segments, engine="faster-whisper", model_size=model_size, audio_path=audio_path, language=language)
    payload["engine_info"] = info_payload
    return payload, info_payload


def _run_openai_whisper(audio_path: Path, *, model_size: str, language: str | None, device: str) -> tuple[dict[str, Any], dict[str, Any]]:
    import whisper

    model = whisper.load_model(model_size, device=device)
    kwargs: dict[str, Any] = {"fp16": False}
    if language:
        kwargs["language"] = language
    result = model.transcribe(str(audio_path), **kwargs)
    raw_segments = []
    for seg in result.get("segments", []):
        raw_segments.append({"start": float(seg["start"]), "end": float(seg["end"]), "text": seg.get("text", "")})
    info_payload = {"detected_language": result.get("language")}
    payload = _segments_to_payload(raw_segments, engine="openai-whisper", model_size=model_size, audio_path=audio_path, language=language)
    payload["engine_info"] = info_payload
    return payload, info_payload


def update_project_reports(project_dir: Path, result: dict[str, Any]) -> None:
    state_path = project_dir / "project_state.json"
    state = read_json(state_path)
    if state:
        state.setdefault("stage_reports", {})["verselock_whisper_probe"] = result
        state["updated_at"] = now_utc_iso()
        write_json(state_path, state)

    manifest_path = project_dir / "asset_manifest.json"
    manifest = read_json(manifest_path)
    manifest.setdefault("sync", {})["whisper_probe"] = {
        "ok": result.get("ok"),
        "engine": result.get("engine"),
        "model_size": result.get("model_size"),
        "transcript_json": result.get("output_json"),
        "rough_lrc": result.get("output_lrc"),
        "segment_count": result.get("segment_count"),
        "updated_at": now_utc_iso(),
    }
    write_json(manifest_path, manifest)


def run_whisper_probe(
    project: str | Path,
    *,
    model_size: str = "tiny",
    engine: str = "auto",
    language: str | None = None,
    device: str = "cpu",
    compute_type: str = "int8",
    force: bool = False,
) -> dict[str, Any]:
    project_dir = Path(project)
    if not project_dir.exists():
        return {"ok": False, "mode": "whisper_probe", "reason": f"Project folder not found: {project_dir}"}

    audio_path = find_audio_file(project_dir)
    if not audio_path:
        return {
            "ok": False,
            "mode": "whisper_probe",
            "reason": "No audio file found in project/audio. Expected source_audio.m4a/mp3/wav/webm/mp4.",
            "project_dir": str(project_dir),
        }

    sync_dir = project_dir / "sync"
    output_json = sync_dir / "whisper_transcript.json"
    output_lrc = sync_dir / "whisper_rough_lrc.lrc"
    report_path = sync_dir / "whisper_probe_report.json"

    if output_json.exists() and output_lrc.exists() and not force:
        existing = read_json(output_json)
        result = {
            "ok": True,
            "mode": "whisper_probe",
            "reused_existing_outputs": True,
            "engine": existing.get("engine"),
            "model_size": existing.get("model_size"),
            "audio": str(audio_path),
            "output_json": str(output_json),
            "output_lrc": str(output_lrc),
            "segment_count": existing.get("segment_count", 0),
            "project_dir": str(project_dir),
            "note": "This is a Whisper transcription probe, not final lyric alignment.",
        }
        update_project_reports(project_dir, result)
        write_json(report_path, result)
        return result

    try:
        if engine in {"auto", "faster-whisper"}:
            try:
                payload, _ = _run_faster_whisper(
                    audio_path,
                    model_size=model_size,
                    language=language,
                    device=device,
                    compute_type=compute_type,
                )
            except ModuleNotFoundError:
                if engine == "faster-whisper":
                    raise
                payload, _ = _run_openai_whisper(audio_path, model_size=model_size, language=language, device=device)
        elif engine == "openai-whisper":
            payload, _ = _run_openai_whisper(audio_path, model_size=model_size, language=language, device=device)
        else:
            return {"ok": False, "mode": "whisper_probe", "reason": f"Unknown engine: {engine}"}
    except ModuleNotFoundError as exc:
        missing = str(exc).split("'")[-2] if "'" in str(exc) else str(exc)
        return {
            "ok": False,
            "mode": "whisper_probe",
            "reason": f"Whisper dependency is not installed: {missing}",
            "install_recommended": "pip install faster-whisper",
            "alternative": "pip install openai-whisper",
            "project_dir": str(project_dir),
        }
    except Exception as exc:  # noqa: BLE001
        result = {
            "ok": False,
            "mode": "whisper_probe",
            "reason": str(exc),
            "audio": str(audio_path),
            "project_dir": str(project_dir),
        }
        write_json(report_path, result)
        update_project_reports(project_dir, result)
        return result

    sync_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_json, payload)
    atomic_text(output_lrc, _payload_to_lrc(payload))

    result = {
        "ok": True,
        "mode": "whisper_probe",
        "reused_existing_outputs": False,
        "engine": payload.get("engine"),
        "model_size": payload.get("model_size"),
        "language": language,
        "audio": str(audio_path),
        "output_json": str(output_json),
        "output_lrc": str(output_lrc),
        "segment_count": payload.get("segment_count", 0),
        "project_dir": str(project_dir),
        "note": "This proves Whisper can generate timestamped transcription from audio. It is not final lyric-to-song alignment yet.",
    }
    write_json(report_path, result)
    update_project_reports(project_dir, result)
    return result
