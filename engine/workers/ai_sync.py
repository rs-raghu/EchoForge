"""
engine/workers/ai_sync.py

AI Sync worker — runs Demucs vocal isolation then Whisper forced alignment,
or fast-paths through LRC→timestamps.json conversion when a pre-synced
.lrc already exists in the workspace.

Bug 2 fix — sys.exit(0/1) instead of return True/False.

CLI USAGE:
    python ai_sync.py --workspace ./workspaces/abc123
"""

import argparse
import json
import os
import re
import subprocess
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from utils.logger import get_logger

log = get_logger(__name__)

try:
    import whisper_timestamped as whisper
except ImportError:
    log.error("❌ 'whisper-timestamped' not installed.")
    whisper = None


# ─── Demucs ───────────────────────────────────────────────────────────────────

def run_demucs(audio_path: str, workspace_dir: str) -> str | None:
    """
    Isolate vocals with Demucs htdemucs model.
    Returns path to vocals file (mp3 or wav), or None on failure.
    """
    log.info("🎙️  Starting Demucs vocal isolation...")
    try:
        result = subprocess.run(
            [
                "demucs",
                "--two-stems=vocals",
                "--out", workspace_dir,
                audio_path,
            ],
            capture_output=True,
            text=True,
        )

        if result.returncode != 0:
            log.error("❌ Demucs failed (exit %d):\n%s", result.returncode, result.stdout)
            return None

        base = os.path.splitext(os.path.basename(audio_path))[0]
        for ext in ("mp3", "wav"):
            candidate = os.path.join(workspace_dir, "htdemucs", base, f"vocals.{ext}")
            if os.path.exists(candidate):
                log.info("✅ Vocals saved: %s", candidate)
                return candidate

        log.error("❌ Demucs ran but vocals file not found.")
        return None

    except Exception as exc:
        log.exception("❌ Demucs crashed: %s", exc)
        return None


# ─── Whisper alignment ────────────────────────────────────────────────────────

def run_whisper_sync(vocals_path: str, lyrics_txt_path: str, workspace_dir: str) -> bool:
    """
    Force-align lyrics.txt to vocals using whisper-timestamped.
    Saves raw output to timestamps_raw.json and clean output to timestamps.json.
    """
    if not whisper:
        log.error("❌ whisper-timestamped not available.")
        return False

    log.info("🧠 Running Whisper forced alignment...")
    try:
        with open(lyrics_txt_path, "r", encoding="utf-8") as fh:
            lyrics_text = fh.read()

        model  = whisper.load_model("base", device="cpu")
        result = whisper.transcribe(
            model, vocals_path,
            initial_prompt=lyrics_text,
            language="en",
        )

        # Save raw output as backup
        raw_path = os.path.join(workspace_dir, "timestamps_raw.json")
        with open(raw_path, "w", encoding="utf-8") as fh:
            json.dump(result, fh, indent=2)

        # Convert to the clean segments format expected by LyricVideo.tsx
        segments = []
        for seg in result.get("segments", []):
            words = [
                {"word": w["text"].strip(), "start": w["start"], "end": w["end"]}
                for w in seg.get("words", [])
                if w.get("text", "").strip()
            ]
            segments.append({
                "text":  seg["text"].strip(),
                "start": seg["start"],
                "end":   seg["end"],
                "words": words,
            })

        ts_path = os.path.join(workspace_dir, "timestamps.json")
        with open(ts_path, "w", encoding="utf-8") as fh:
            json.dump({"segments": segments}, fh, indent=2, ensure_ascii=False)

        log.info("✅ Whisper alignment complete — %d segments → %s", len(segments), ts_path)
        return True

    except Exception as exc:
        log.exception("❌ Whisper alignment failed: %s", exc)
        return False


# ─── LRC fast path ────────────────────────────────────────────────────────────

def process_lrc_timestamps(lrc_path: str, workspace_dir: str) -> bool:
    """
    Parse a pre-synced .lrc file into timestamps.json without Demucs/Whisper.
    Each segment gets word-level data set to an empty list (no word-by-word
    highlighting for LRC-sourced lyrics).
    """
    log.info("⚡ Processing pre-synced LRC: %s", lrc_path)
    try:
        segments = []
        with open(lrc_path, "r", encoding="utf-8") as fh:
            for line in fh:
                m = re.match(r"\[(\d{2}):(\d{2}\.\d{2,3})\](.*)", line)
                if m:
                    start = int(m.group(1)) * 60 + float(m.group(2))
                    text  = m.group(3).strip()
                    if text:
                        segments.append({"start": start, "end": start + 3.0,
                                         "text": text, "words": []})

        if not segments:
            log.error("❌ No timestamped lines found in LRC.")
            return False

        # Fix end times using the start of the next segment
        for i in range(len(segments) - 1):
            segments[i]["end"] = segments[i + 1]["start"] - 0.05

        ts_path = os.path.join(workspace_dir, "timestamps.json")
        with open(ts_path, "w", encoding="utf-8") as fh:
            json.dump({"segments": segments}, fh, indent=2, ensure_ascii=False)

        log.info("✅ LRC → timestamps.json (%d segments)", len(segments))
        return True

    except Exception as exc:
        log.exception("❌ LRC processing failed: %s", exc)
        return False


# ─── Main entry ───────────────────────────────────────────────────────────────

def process(song: dict) -> bool:
    """
    Decide which sync path to take and execute it.
    Returns True on success, False on any failure.
    """
    workspace_dir = song.get("workspace_dir")
    if not workspace_dir:
        log.error("❌ Missing workspace_dir.")
        return False

    lrc_path  = os.path.join(workspace_dir, "lyrics.lrc")
    txt_path  = os.path.join(workspace_dir, "lyrics.txt")
    audio_path = os.path.join(workspace_dir, "audio.mp3")
    ts_path   = os.path.join(workspace_dir, "timestamps.json")

    if os.path.exists(ts_path):
        log.info("✅ timestamps.json already exists — skipping AI sync.")
        return True

    if os.path.exists(lrc_path):
        log.info("⏩ Pre-synced LRC found — fast path (no Demucs/Whisper).")
        return process_lrc_timestamps(lrc_path, workspace_dir)

    if os.path.exists(txt_path):
        if not os.path.exists(audio_path):
            log.error("❌ audio.mp3 missing — cannot run Demucs.")
            return False

        vocals = run_demucs(audio_path, workspace_dir)
        if not vocals:
            return False

        return run_whisper_sync(vocals, txt_path, workspace_dir)

    log.error("❌ No lyrics file (.lrc or .txt) found in workspace.")
    return False


# ── CLI ────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="EchoForge AI Sync Worker")
    parser.add_argument("--workspace", required=True, help="Path to workspace folder")
    parser.add_argument("--title",     default="Test", help="Song title (for logging)")
    args = parser.parse_args()

    song = {"title": args.title, "workspace_dir": args.workspace}
    ok   = process(song)
    print(f"\n{'✅ Success' if ok else '❌ Failed'}")
    sys.exit(0 if ok else 1)
