"""
render_engine.py

Picks the next ASSETS_READY song from the pipeline, stages all files into
the Remotion public/ folder, and triggers the renderer.

Key responsibilities:
  - Background selection  : Assets/backgrounds/{rank % 30 + 1}.jpg  (modulo-30)
  - Audio offset calc     : If first lyric < 5 s, delay audio so lyrics land
                            exactly when the 5 s intro ends.
  - audioConfig.json      : Written to public/ so LyricVideo.tsx and Root.tsx
                            both know the delay value without any build-time env.
  - Output naming         : Output/YYYY-MM-DD-SongTitle.mp4
  - DB update             : Marks job as VIDEO_CREATED on success.
"""

import json
import os
import re
import shutil
import subprocess
import glob
from datetime import datetime

import db_manager

# ─── Configuration ────────────────────────────────────────────────────────────
_HERE            = os.path.dirname(os.path.abspath(__file__))
ASSETS_DIR       = os.path.normpath(os.path.join(_HERE, "..", "Assets"))
BACKGROUNDS_DIR  = os.path.join(ASSETS_DIR, "backgrounds")
LOGO_PATH        = os.path.normpath(os.path.join(_HERE, "..", "Assets", "logo.png"))
VIDEO_ENGINE_DIR = os.path.normpath(os.path.join(_HERE, "..", "video-engine"))
REACT_PUBLIC_DIR = os.path.join(VIDEO_ENGINE_DIR, "public")
OUTPUT_DIR       = os.path.normpath(os.path.join(_HERE, "..", "Output"))

INTRO_DURATION   = 5.0   # 2 s logo + 3 s details


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _clean_name(name: str) -> str:
    """Strip OS-illegal characters — mirrors auto_discovery.clean_folder_name."""
    return re.sub(r'[\\/*?:"<>|]', "", name).strip()


def _select_background(rank: int) -> str:
    """
    Return the path to the background image for this song's rank.
    Images are named 1.jpg … 30.jpg in Assets/backgrounds/.
    The modulo wraps cleanly: rank 0 → 1.jpg, rank 30 → 1.jpg, etc.
    rank=0 is used for manual entries; it maps to 1.jpg.
    """
    index = (max(0, rank - 1) % 30) + 1   # ranks are 1-based on the chart
    return os.path.join(BACKGROUNDS_DIR, f"{index}.jpg")


def _compute_audio_delay(timestamps_path: str) -> float:
    """
    Calculate how many seconds to delay the audio track inside the video.

    Logic:
      - If the first lyric starts at  T >= INTRO_DURATION  →  delay = 0.
        The song plays from frame 0; the intro (logo + details) runs over
        whatever musical intro the track already has.
      - If the first lyric starts at  T < INTRO_DURATION   →  delay = 5 - T.
        We push the audio forward so the first lyric lands exactly when the
        5-second intro screen ends.

    Examples:
      firstLyricAt = 19.64 s  →  delay = 0    (Golden)
      firstLyricAt =  3.00 s  →  delay = 2.0  (audio starts at video t=2s)
      firstLyricAt =  0.50 s  →  delay = 4.5  (pure-hook song)
    """
    with open(timestamps_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    segments = data.get("segments", [])
    if not segments:
        return 0.0

    first_start = segments[0]["start"]
    delay = max(0.0, INTRO_DURATION - first_start)
    return round(delay, 3)


def _get_ready_job():
    """
    Pull the first ASSETS_READY job from the database.
    Returns (video_id, title, artist, rank) or None.
    """
    import sqlite3
    db_path = db_manager.DB_PATH
    try:
        conn   = sqlite3.connect(db_path, timeout=30, check_same_thread=False)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT video_id, title, artist FROM pipeline_jobs WHERE status = ? LIMIT 1",
            ("ASSETS_READY",),
        )
        row = cursor.fetchone()
        conn.close()
        return row  # (video_id, title, artist) or None
    except Exception as e:
        print(f"❌ DB query failed: {e}")
        return None


def _find_asset_folder(title: str) -> str | None:
    """Locate the song's workspace folder inside Assets/."""
    safe = _clean_name(title)
    folders = glob.glob(os.path.join(ASSETS_DIR, f"*-{safe}*"))
    return folders[0] if folders else None


# ─── Main entry point ─────────────────────────────────────────────────────────

def render_video():
    """
    Full render pipeline:
      1. Fetch next ASSETS_READY job.
      2. Load metadata to get rank for background selection.
      3. Compute audio delay from timestamps.
      4. Stage all public/ assets (audio, timestamps, metadata, bg, logo,
         audioConfig).
      5. Run Remotion CLI.
      6. Move output to Output/YYYY-MM-DD-Title.mp4.
      7. Update DB → VIDEO_CREATED.
    """
    print("🎬 BOOTING RENDER ENGINE...")
    db_manager.init_db()

    # ── 1. Job queue ──────────────────────────────────────────────────────────
    job = _get_ready_job()
    if not job:
        print("💤 No songs in ASSETS_READY status. Nothing to render.")
        return

    video_id, title, artist = job
    print(f"\n🚀 Rendering: {title}  —  {artist}")

    # ── 2. Locate asset folder ────────────────────────────────────────────────
    asset_folder = _find_asset_folder(title)
    if not asset_folder:
        print(f"❌ Asset folder not found for: {title}")
        return
    print(f"   📂 Asset folder: {asset_folder}")

    # ── 3. Load metadata (for rank) ───────────────────────────────────────────
    metadata_path    = os.path.join(asset_folder, "metadata.json")
    timestamps_path  = os.path.join(asset_folder, "timestamps.json")

    with open(metadata_path, "r", encoding="utf-8") as f:
        meta = json.load(f)

    rank = int(meta.get("rank", 0))

    # ── 4. Select background ──────────────────────────────────────────────────
    bg_source = _select_background(rank)
    bg_index  = (max(0, rank - 1) % 30) + 1
    print(f"   🖼️  Background: {bg_index}.jpg  (rank {rank} → index {bg_index})")

    if not os.path.exists(bg_source):
        print(f"❌ Background not found: {bg_source}")
        return

    # ── 5. Compute audio delay ────────────────────────────────────────────────
    audio_delay = _compute_audio_delay(timestamps_path)
    if audio_delay > 0:
        first_lyric = timestamps_json_first_start(timestamps_path)
        print(f"   ⏱️  First lyric at {first_lyric:.2f}s → audio delayed by {audio_delay}s in video")
    else:
        print(f"   ⏱️  First lyric >= 5 s → no audio delay needed")

    # ── 6. Stage files into video-engine/public/ ──────────────────────────────
    os.makedirs(REACT_PUBLIC_DIR, exist_ok=True)
    print("   📦 Staging assets into video-engine/public/...")

    # Required files from asset folder
    required = {
        "audio.mp3":       os.path.join(asset_folder, "audio.mp3"),
        "timestamps.json": timestamps_path,
        "metadata.json":   metadata_path,
    }
    for dest_name, src_path in required.items():
        if not os.path.exists(src_path):
            print(f"   ❌ Missing required asset: {src_path}")
            return
        shutil.copy(src_path, os.path.join(REACT_PUBLIC_DIR, dest_name))
        print(f"   ✅ {dest_name}")

    # Background → always named bg.jpg in public/
    shutil.copy(bg_source, os.path.join(REACT_PUBLIC_DIR, "bg.jpg"))
    print(f"   ✅ bg.jpg  ({bg_index}.jpg)")

    # Logo
    if not os.path.exists(LOGO_PATH):
        print(f"   ⚠️  logo.png not found at {LOGO_PATH} — continuing without it")
    else:
        shutil.copy(LOGO_PATH, os.path.join(REACT_PUBLIC_DIR, "logo.png"))
        print(f"   ✅ logo.png")

    # audioConfig.json — tells LyricVideo how many seconds to delay the <Audio>
    audio_config = {"audioDelayInVideo": audio_delay}
    with open(os.path.join(REACT_PUBLIC_DIR, "audioConfig.json"), "w") as f:
        json.dump(audio_config, f, indent=2)
    print(f"   ✅ audioConfig.json  (delay={audio_delay}s)")

    # ── 7. Run Remotion renderer ──────────────────────────────────────────────
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    today     = datetime.now().strftime("%Y-%m-%d")
    safe_title = _clean_name(title)
    out_name  = f"{today}-{safe_title}.mp4"
    out_path  = os.path.abspath(os.path.join(OUTPUT_DIR, out_name))

    print(f"\n   🎞️  Rendering → {out_path}")
    print("   (This may take several minutes...)\n")

    use_shell = os.name == "nt"   # shell=True required for npx on Windows
    command   = [
        "npx", "remotion", "render",
        "EchoForgeLyricVideo",
        out_path,
    ]

    try:
        subprocess.run(
            command,
            cwd=VIDEO_ENGINE_DIR,
            check=True,
            shell=use_shell,
        )
        print(f"\n✅ Render complete!  →  {out_path}")
        db_manager.update_song_status(video_id, "VIDEO_CREATED")

    except subprocess.CalledProcessError as e:
        print(f"\n❌ Remotion render failed: {e}")
    except Exception as e:
        print(f"\n❌ Unexpected error during render: {e}")
        import traceback
        traceback.print_exc()


def timestamps_json_first_start(path: str) -> float:
    """Helper to read the first segment start time."""
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    segs = data.get("segments", [])
    return segs[0]["start"] if segs else 0.0


# ─── Standalone ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    render_video()