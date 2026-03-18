"""
render_engine.py

Stages all asset files into the Remotion public/ folder and triggers the renderer.

Can be called two ways:
  1. From master_controller.py with specific song details (primary — no DB query needed).
  2. Standalone via __main__ — picks the next ASSETS_READY job from the DB.

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
import glob
import shutil
import subprocess
from datetime import datetime

import db_manager
from config import (
    ASSETS_DIR, BACKGROUNDS_DIR, LOGO_PATH,
    VIDEO_ENGINE_DIR, REACT_PUBLIC_DIR, OUTPUT_DIR,
    INTRO_DURATION, NUM_BACKGROUNDS, THUMBNAIL_TIMESTAMP,
)


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _clean_name(name: str) -> str:
    """Strip OS-illegal characters — mirrors auto_discovery.clean_folder_name."""
    return re.sub(r'[\\/*?:"<>|\[\]]', "", name).strip()


def _select_background(rank: int) -> str:
    """
    Return the path to the background image for this song's rank.
    Images are named 1.jpg … 30.jpg in Assets/backgrounds/.
    rank=0 is used for manual entries and maps to 1.jpg.
    """
    index = (max(0, rank - 1) % NUM_BACKGROUNDS) + 1
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
      firstLyricAt = 19.64 s  →  delay = 0    (song has its own intro)
      firstLyricAt =  3.00 s  →  delay = 2.0  (audio starts at video t=2s)
      firstLyricAt =  0.50 s  →  delay = 4.5  (pure-hook song)
    """
    try:
        with open(timestamps_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        print(f"   ⚠️  Could not read timestamps.json ({e}) — defaulting delay to 0.")
        return 0.0

    segments = data.get("segments", [])
    if not segments:
        print("   ⚠️  timestamps.json has no segments — defaulting delay to 0.")
        return 0.0

    first_start = segments[0].get("start", 0.0)
    delay = max(0.0, INTRO_DURATION - first_start)
    return round(delay, 3)


def _find_asset_folder(workspace: str | None, title: str) -> str | None:
    """
    Locate the song's workspace folder.

    Priority:
      1. Use the workspace path passed in directly (most reliable).
      2. Fall back to glob search inside ASSETS_DIR by sanitised title.
         Uses glob.escape() so titles with [ ] don't break the pattern.
    """
    # Direct path passed in from master_controller
    if workspace and os.path.isdir(workspace):
        return workspace

    # Glob fallback (standalone / manual usage)
    safe = _clean_name(title)
    pattern = os.path.join(ASSETS_DIR, f"*-{glob.escape(safe)}*")
    folders = glob.glob(pattern)
    if folders:
        # Sort by modification time, return newest — handles duplicate date prefixes
        folders.sort(key=os.path.getmtime, reverse=True)
        return folders[0]

    return None


def _get_ready_job():
    """
    Pull the first ASSETS_READY job from the database using the shared lock.
    Returns (video_id, title, artist) or None.
    """
    with db_manager._DB_LOCK:
        conn   = db_manager._get_conn()
        cursor = conn.cursor()
        try:
            cursor.execute(
                "SELECT video_id, title, artist FROM pipeline_jobs WHERE status = ? LIMIT 1",
                ("ASSETS_READY",),
            )
            row = cursor.fetchone()
        except Exception as e:
            print(f"❌ DB query failed: {e}")
            row = None
        finally:
            conn.close()
    return row


# ─── Main entry point ─────────────────────────────────────────────────────────

def render_video(
    video_id:  str | None = None,
    title:     str | None = None,
    artist:    str | None = None,
    workspace: str | None = None,
) -> bool:
    """
    Full render pipeline. Returns True on success, False on failure.

    When called from master_controller, video_id / title / artist / workspace
    are all provided — no DB query needed.

    When called standalone (__main__), all args are None and the function
    queries the DB for the next ASSETS_READY job.
    """
    print("\n🎬 BOOTING RENDER ENGINE...")
    db_manager.init_db()

    # ── 1. Resolve job details ────────────────────────────────────────────────
    if not (video_id and title and artist):
        # Standalone mode — query DB
        job = _get_ready_job()
        if not job:
            print("💤 No songs in ASSETS_READY status. Nothing to render.")
            return False
        video_id, title, artist = job
        workspace = None   # will be resolved by glob below

    print(f"\n🚀 Rendering: {title}  —  {artist}  (ID: {video_id})")

    # ── 2. Locate asset folder ────────────────────────────────────────────────
    asset_folder = _find_asset_folder(workspace, title)
    if not asset_folder:
        print(f"❌ Asset folder not found for: {title}")
        return False
    print(f"   📂 Asset folder: {asset_folder}")

    # ── 3. Validate required files exist ─────────────────────────────────────
    metadata_path   = os.path.join(asset_folder, "metadata.json")
    timestamps_path = os.path.join(asset_folder, "timestamps.json")
    audio_path      = os.path.join(asset_folder, "audio.mp3")

    missing = [p for p in [metadata_path, timestamps_path, audio_path] if not os.path.exists(p)]
    if missing:
        for m in missing:
            print(f"   ❌ Missing required file: {m}")
        return False

    # ── 4. Load metadata (for rank) ───────────────────────────────────────────
    try:
        with open(metadata_path, "r", encoding="utf-8") as f:
            meta = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        print(f"❌ Could not read metadata.json: {e}")
        return False

    rank = int(meta.get("rank", 0))

    # ── 5. Select background ──────────────────────────────────────────────────
    bg_source = _select_background(rank)
    bg_index  = (max(0, rank - 1) % 30) + 1
    print(f"   🖼️  Background: {bg_index}.jpg  (rank {rank})")

    if not os.path.exists(bg_source):
        print(f"❌ Background image not found: {bg_source}")
        print(f"   Make sure Assets/backgrounds/{bg_index}.jpg exists.")
        return False

    # ── 6. Compute audio delay ────────────────────────────────────────────────
    audio_delay = _compute_audio_delay(timestamps_path)
    if audio_delay > 0:
        first_lyric = _first_lyric_start(timestamps_path)
        print(f"   ⏱️  First lyric at {first_lyric:.2f}s → audio delayed by {audio_delay}s")
    else:
        print(f"   ⏱️  First lyric >= 5s → no audio delay needed")

    # ── 7. Stage files into video-engine/public/ ──────────────────────────────
    os.makedirs(REACT_PUBLIC_DIR, exist_ok=True)
    print("\n   📦 Staging assets into video-engine/public/...")

    files_to_copy = {
        "audio.mp3":       audio_path,
        "timestamps.json": timestamps_path,
        "metadata.json":   metadata_path,
    }
    for dest_name, src_path in files_to_copy.items():
        shutil.copy(src_path, os.path.join(REACT_PUBLIC_DIR, dest_name))
        print(f"   ✅ {dest_name}")

    # Background → always named bg.jpg in public/
    shutil.copy(bg_source, os.path.join(REACT_PUBLIC_DIR, "bg.jpg"))
    print(f"   ✅ bg.jpg  ({bg_index}.jpg)")

    # Logo — optional, warn but don't abort
    if not os.path.exists(LOGO_PATH):
        print(f"   ⚠️  logo.png not found at {LOGO_PATH} — rendering without logo")
    else:
        shutil.copy(LOGO_PATH, os.path.join(REACT_PUBLIC_DIR, "logo.png"))
        print(f"   ✅ logo.png")

    # audioConfig.json — tells LyricVideo how many seconds to delay the <Audio>
    audio_config = {"audioDelayInVideo": audio_delay}
    with open(os.path.join(REACT_PUBLIC_DIR, "audioConfig.json"), "w") as f:
        json.dump(audio_config, f, indent=2)
    print(f"   ✅ audioConfig.json  (delay={audio_delay}s)")

    # ── 8. Run Remotion renderer ──────────────────────────────────────────────
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    today      = datetime.now().strftime("%Y-%m-%d")
    safe_title = _clean_name(title)
    out_name   = f"{today}-{safe_title}.mp4"
    out_path   = os.path.abspath(os.path.join(OUTPUT_DIR, out_name))

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
        return True

    except subprocess.CalledProcessError as e:
        print(f"\n❌ Remotion render failed (exit code {e.returncode}).")
        print("   Check the Remotion output above for details.")
        return False

    except Exception as e:
        print(f"\n❌ Unexpected error during render: {e}")
        import traceback
        traceback.print_exc()
        return False


# ─── Internal helper ──────────────────────────────────────────────────────────

def _first_lyric_start(path: str) -> float:
    """Read the start time of the first lyric segment."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        segs = data.get("segments", [])
        return segs[0].get("start", 0.0) if segs else 0.0
    except Exception:
        return 0.0


# ─── Standalone ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    render_video()