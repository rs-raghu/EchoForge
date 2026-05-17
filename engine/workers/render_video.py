"""
engine/workers/render_video.py

Renders the final lyric video using Remotion.
Stages assets into remotion/public/, runs the CLI, saves final_video.mp4
back to the workspace.

Bug 2 fix — sys.exit(0/1) instead of return True/False.

CLI USAGE:
    python render_video.py --workspace ./workspaces/abc123 --title "Song" --artist "Artist"
"""

import argparse
import json
import os
import shutil
import subprocess
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from utils.logger import get_logger

log = get_logger(__name__)

ROOT_DIR    = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
REMOTION_DIR = os.path.join(ROOT_DIR, "remotion")
PUBLIC_DIR   = os.path.join(REMOTION_DIR, "public")
FPS = 30


def _get_audio_duration_seconds(audio_path: str) -> float | None:
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                audio_path,
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            return float(result.stdout.strip())
    except Exception as exc:
        log.warning("Could not read audio duration with ffprobe: %s", exc)
    return None


def _get_timestamp_duration_seconds(ts_path: str) -> float | None:
    try:
        with open(ts_path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        segments = data.get("segments", [])
        if segments:
            return float(max(segment.get("end", 0) for segment in segments))
    except Exception as exc:
        log.warning("Could not read timestamp duration: %s", exc)
    return None


def render(song: dict) -> bool:
    """
    Render final_video.mp4 for *song* into workspace_dir.
    Returns True on success, False on any failure.
    """
    workspace_dir = song.get("workspace_dir")
    title         = song.get("title", "Unknown")
    artist        = song.get("artist", "Unknown")

    if not workspace_dir:
        log.error("❌ Missing workspace_dir.")
        return False

    audio_path  = os.path.join(workspace_dir, "audio.mp3")
    ts_path     = os.path.join(workspace_dir, "timestamps.json")
    output_video = os.path.join(workspace_dir, "final_video.mp4")

    if os.path.exists(output_video):
        log.info("✅ Video already rendered — skipping.")
        return True

    if not os.path.exists(audio_path):
        log.error("❌ audio.mp3 missing from workspace.")
        return False
    if not os.path.exists(ts_path):
        log.error("❌ timestamps.json missing from workspace.")
        return False

    if not os.path.exists(REMOTION_DIR):
        log.error("❌ Remotion project not found at %s", REMOTION_DIR)
        return False

    log.info("🎬 Preparing Remotion render for '%s'...", title)

    try:
        duration_seconds = (
            _get_audio_duration_seconds(audio_path)
            or _get_timestamp_duration_seconds(ts_path)
            or 60
        )
        duration_in_frames = max(int((duration_seconds + 2) * FPS), FPS)

        os.makedirs(PUBLIC_DIR, exist_ok=True)

        # Stage assets
        shutil.copy(audio_path, os.path.join(PUBLIC_DIR, "audio.mp3"))
        shutil.copy(ts_path,    os.path.join(PUBLIC_DIR, "timestamps.json"))

        # Write props file
        props = {
            "title":         title,
            "artist":        artist,
            "audioUrl":      "audio.mp3",
            "timestampsUrl": "timestamps.json",
            "durationInFrames": duration_in_frames,
        }
        props_file = os.path.join(REMOTION_DIR, "current_props.json")
        with open(props_file, "w", encoding="utf-8") as fh:
            json.dump(props, fh)

        log.info("🔥 Starting Remotion render engine...")

        use_shell = os.name == "nt"
        proc = subprocess.run(
            [
                "npx", "remotion", "render",
                "src/index.ts",
                "LyricVideo",
                output_video,
                f"--props={props_file}",
            ],
            cwd=REMOTION_DIR,
            capture_output=True,
            text=True,
            shell=use_shell,
        )

        # Clean up staging files (best-effort)
        for staged in ("audio.mp3", "timestamps.json"):
            try:
                os.remove(os.path.join(PUBLIC_DIR, staged))
            except OSError:
                pass
        try:
            os.remove(props_file)
        except OSError:
            pass

        if proc.returncode == 0 and os.path.exists(output_video):
            log.info("✅ Video rendered: %s", output_video)
            return True

        if proc.stdout:
            log.error("Remotion stdout:\n%s", proc.stdout[-4000:])
        if proc.stderr:
            log.error("Remotion stderr:\n%s", proc.stderr[-4000:])
        log.error("❌ Remotion render failed (exit code %d).", proc.returncode)
        return False

    except Exception as exc:
        log.exception("❌ Unexpected render error: %s", exc)
        return False


# ── CLI ────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="EchoForge Render Worker")
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--title",     default="Test Track")
    parser.add_argument("--artist",    default="Test Artist")
    args = parser.parse_args()

    song = {
        "title":         args.title,
        "artist":        args.artist,
        "workspace_dir": args.workspace,
    }
    ok = render(song)
    print(f"\n{'✅ Success' if ok else '❌ Failed'}")
    sys.exit(0 if ok else 1)
