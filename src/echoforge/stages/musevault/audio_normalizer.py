from __future__ import annotations
import os
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from echoforge.core.media import audio_duration
from echoforge.core.storage import atomic_json, file_lock

AUDIO_NAMES = ["source_audio.m4a", "source_audio.mp3", "source_audio.wav", "source_audio.webm", "source_audio.mp4"]


def find_source_audio(project_dir):
    folder = Path(project_dir) / "audio"
    candidates = [folder / name for name in AUDIO_NAMES]
    candidates.extend(sorted(folder.glob("source_audio.*")))
    return next((p for p in candidates if audio_duration(p) is not None), None)


def normalize_project_audio(project_dir, *, force=False):
    project_dir = Path(project_dir)
    folder = project_dir / "audio"
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / "source_audio.m4a"
    with file_lock(folder / "normalization.lock"):
        source = find_source_audio(project_dir)
        result = {"ok": False, "stage": "audio_normalization", "source": str(source) if source else None,
                  "target": str(target), "created_at": datetime.now(timezone.utc).isoformat()}
        if not source:
            result["reason"] = "No valid audio stream found in project/audio (ffprobe is required)."
        elif source == target and not force:
            result.update(ok=True, mode="already_m4a", path=str(target))
        else:
            temporary = folder / f".normalization-{uuid.uuid4().hex}.m4a"
            try:
                subprocess.run(["ffmpeg", "-y", "-i", str(source), "-vn", "-c:a", "aac", "-b:a", "192k", str(temporary)],
                               check=True, capture_output=True, text=True, timeout=1800)
                if audio_duration(temporary) is None:
                    raise ValueError("Converted file contains no valid audio stream")
                os.replace(temporary, target)
                result.update(ok=True, mode="converted_to_m4a", path=str(target))
            except (OSError, ValueError, subprocess.SubprocessError) as exc:
                result["reason"] = f"Audio conversion failed: {exc}"
            finally:
                temporary.unlink(missing_ok=True)
        atomic_json(folder / "audio_normalization_status.json", result)
        return result
