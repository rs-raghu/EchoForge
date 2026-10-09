from __future__ import annotations
import hashlib
import json
import math
import subprocess
from pathlib import Path


def fingerprint(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def audio_duration(path: Path) -> float | None:
    if not path.is_file() or path.stat().st_size == 0:
        return None
    try:
        result = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a:0",
                                 "-show_entries", "stream=codec_type:format=duration", "-of", "json", str(path)],
                                check=True, capture_output=True, text=True, timeout=30)
        data = json.loads(result.stdout)
        seconds = float(data["format"]["duration"])
        return seconds if data.get("streams") and math.isfinite(seconds) and seconds > 0 else None
    except (OSError, ValueError, KeyError, subprocess.SubprocessError):
        return None
