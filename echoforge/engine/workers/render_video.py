"""
engine/workers/render_video.py

Renders the final lyric video using Remotion.
Stages assets into renderer/remotion/public/, runs the CLI, saves final_video.mp4
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
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[3]
sys.path.append(str(ROOT_DIR))

from echoforge.utils.logger import get_logger

log = get_logger(__name__)

REMOTION_DIR = str(ROOT_DIR / "renderer" / "remotion")
PUBLIC_DIR   = os.path.join(REMOTION_DIR, "public")
FPS = 30


def _workspace_file(workspace_dir: str, *relative_paths: str) -> str | None:
    for relative_path in relative_paths:
        candidate = os.path.join(workspace_dir, relative_path)
        if os.path.exists(candidate):
            return candidate
    return None


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


def _load_render_props(workspace_dir: str, title: str, artist: str) -> dict:
    props_path = os.path.join(workspace_dir, "design", "render_props.json")
    props = {"title": title, "artist": artist, "design": {}}
    if os.path.exists(props_path):
        try:
            with open(props_path, "r", encoding="utf-8") as fh:
                saved = json.load(fh)
            if isinstance(saved, dict):
                props.update(saved)
        except Exception as exc:
            log.warning("Could not read render props: %s", exc)
    props["title"] = props.get("title") or title
    props["artist"] = props.get("artist") or artist
    return props


def _output_paths(workspace_dir: str, mode: str) -> tuple[str, str]:
    if mode == "preview":
        archive_dir = os.path.join(workspace_dir, "renders", "previews")
        os.makedirs(archive_dir, exist_ok=True)
        return (
            os.path.join(workspace_dir, "final_video_preview.mp4"),
            os.path.join(archive_dir, "preview_latest.mp4"),
        )
    archive_dir = os.path.join(workspace_dir, "renders", "final")
    os.makedirs(archive_dir, exist_ok=True)
    return (
        os.path.join(workspace_dir, "final_video.mp4"),
        os.path.join(archive_dir, "final_video.mp4"),
    )


def _copy_finished_output(output_video: str, archive_video: str) -> None:
    if os.path.abspath(output_video) != os.path.abspath(archive_video):
        shutil.copyfile(output_video, archive_video)


def render(song: dict, mode: str = "final", preview_duration: float = 45) -> bool:
    """
    Render final_video.mp4 for *song* into workspace_dir.
    Returns True on success, False on any failure.
    """
    workspace_dir = song.get("workspace_dir")
    title         = song.get("title", "Unknown")
    artist        = song.get("artist", "Unknown")
    mode          = "preview" if mode == "preview" else "final"

    if not workspace_dir:
        log.error("❌ Missing workspace_dir.")
        return False

    audio_path  = _workspace_file(workspace_dir, "audio.mp3", "source/audio.mp3")
    ts_path     = _workspace_file(workspace_dir, "timestamps.json", "sync/timestamps.json")
    output_video, archive_video = _output_paths(workspace_dir, mode)

    if False and os.path.exists(output_video):
        log.info("✅ Video already rendered — skipping.")
        return True

    if not audio_path:
        log.error("❌ audio.mp3 missing from workspace.")
        return False
    if not ts_path:
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
        if mode == "preview":
            duration_seconds = max(8, min(duration_seconds, float(preview_duration or 45)))
        duration_in_frames = max(int((duration_seconds + 2) * FPS), FPS)

        os.makedirs(PUBLIC_DIR, exist_ok=True)

        # Stage assets
        shutil.copy(audio_path, os.path.join(PUBLIC_DIR, "audio.mp3"))
        shutil.copy(ts_path,    os.path.join(PUBLIC_DIR, "timestamps.json"))

        # Write props file
        props = _load_render_props(workspace_dir, title, artist)
        props.update(
            {
                "audioUrl": "audio.mp3",
                "timestampsUrl": "timestamps.json",
                "durationInFrames": duration_in_frames,
                "renderMode": mode,
            }
        )
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
            _copy_finished_output(output_video, archive_video)
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
    parser.add_argument("--mode", choices=["preview", "final"], default="final")
    parser.add_argument("--preview-duration", type=float, default=45)
    args = parser.parse_args()

    song = {
        "title":         args.title,
        "artist":        args.artist,
        "workspace_dir": args.workspace,
    }
    ok = render(song, mode=args.mode, preview_duration=args.preview_duration)
    print(f"\n{'✅ Success' if ok else '❌ Failed'}")
    sys.exit(0 if ok else 1)
