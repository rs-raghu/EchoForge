"""
render_engine.py

Stages asset files into the Remotion public/ folder and triggers the renderer.

Changes
───────
• Bug 5   : _get_ready_job() now calls db_manager.get_assets_ready_job() instead
             of directly accessing private _DB_LOCK / _get_conn symbols.
• Feature 7: Respects a pinned_bg user setting (set via /changebg in the bot).
             If pinned_bg is set in DB, that image is always used instead of the
             rank-modulo background. Falls back to rank-based selection if not set.

CLI USAGE:
    python render_engine.py
    python render_engine.py --video-id abc --title "Song" --artist "Art" --workspace ./ws
"""

import argparse
import glob
import json
import os
import re
import shutil
import subprocess
from datetime import datetime

import db_manager
from config import (
    ASSETS_DIR, BACKGROUNDS_DIR, LOGO_PATH,
    VIDEO_ENGINE_DIR, REACT_PUBLIC_DIR, OUTPUT_DIR,
    INTRO_DURATION, NUM_BACKGROUNDS, THUMBNAIL_TIMESTAMP,
)
from logger import get_logger

log = get_logger(__name__)

FONTS_PUBLIC_DIR = os.path.join(REACT_PUBLIC_DIR, "fonts")


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _clean_name(name: str) -> str:
    return re.sub(r'[\\/*?:"<>|\[\]]', "", name).strip()


def _select_background(rank: int) -> str:
    """
    Return the background image path for this song's chart rank.

    Feature 7: If the user has pinned a custom background via /changebg,
    that path is used instead of the rank-modulo selection.
    Falls back to rank-based 1.jpg–30.jpg selection if not set or file missing.
    """
    db_manager.init_db()
    pinned = db_manager.get_setting("pinned_bg")
    if pinned and os.path.isfile(pinned):
        log.info("   🖼️  Using pinned background: %s", pinned)
        return pinned

    index = (max(0, rank - 1) % NUM_BACKGROUNDS) + 1
    return os.path.join(BACKGROUNDS_DIR, f"{index}.jpg")


def _compute_audio_delay(timestamps_path: str) -> float:
    try:
        with open(timestamps_path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (json.JSONDecodeError, OSError) as exc:
        log.warning("⚠️  Could not read timestamps.json (%s) — delay defaults to 0.", exc)
        return 0.0

    segments = data.get("segments", [])
    if not segments:
        log.warning("⚠️  timestamps.json has no segments — delay defaults to 0.")
        return 0.0

    first_start = segments[0].get("start", 0.0)
    return round(max(0.0, INTRO_DURATION - first_start), 3)


def _first_lyric_start(path: str) -> float:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        segs = data.get("segments", [])
        return segs[0].get("start", 0.0) if segs else 0.0
    except Exception:
        return 0.0


def _find_asset_folder(workspace: str | None, title: str) -> str | None:
    if workspace and os.path.isdir(workspace):
        return workspace
    safe    = _clean_name(title)
    pattern = os.path.join(ASSETS_DIR, f"*-{glob.escape(safe)}*")
    folders = glob.glob(pattern)
    if folders:
        folders.sort(key=os.path.getmtime, reverse=True)
        return folders[0]
    return None


# ─── Bug 5 fix: use public db_manager function instead of private symbols ─────

def _get_ready_job() -> tuple | None:
    """
    Return (video_id, title, artist) for the first ASSETS_READY job.
    Previously accessed db_manager._DB_LOCK and db_manager._get_conn directly;
    now uses the public db_manager.get_assets_ready_job() instead.
    """
    return db_manager.get_assets_ready_job()


# ─── Font staging ─────────────────────────────────────────────────────────────

def _stage_fonts() -> dict:
    """
    Read font preferences from DB, copy .ttf/.otf files into public/fonts/,
    and return a fontConfig dict for LyricVideo.tsx.
    """
    db_manager.init_db()
    fonts = db_manager.get_font_paths()
    os.makedirs(FONTS_PUBLIC_DIR, exist_ok=True)

    config = {
        "titleFont": "", "artistFont": "", "lyricsFont": "",
        "titleFontFile": None, "artistFontFile": None, "lyricsFontFile": None,
    }
    mapping = {
        "title":  ("titleFont",  "titleFontFile"),
        "artist": ("artistFont", "artistFontFile"),
        "lyrics": ("lyricsFont", "lyricsFontFile"),
    }

    for role, (family_key, file_key) in mapping.items():
        src = fonts.get(role)
        if not src or not os.path.isfile(src):
            if src:
                log.warning("⚠️  Font file not found for %s: %s", role, src)
            continue
        filename = os.path.basename(src)
        dest     = os.path.join(FONTS_PUBLIC_DIR, filename)
        try:
            shutil.copy2(src, dest)
            log.info("   ✅ Font staged: %s → public/fonts/%s", role, filename)
            family              = os.path.splitext(filename)[0].replace("_", " ").replace("-", " ")
            config[family_key]  = family
            config[file_key]    = filename
        except Exception as exc:
            log.warning("⚠️  Could not stage font '%s': %s", src, exc)

    return config


# ─── Main entry point ─────────────────────────────────────────────────────────

def render_video(
    video_id:  str | None = None,
    title:     str | None = None,
    artist:    str | None = None,
    workspace: str | None = None,
) -> bool:
    """Full render pipeline. Returns True on success, False on failure."""
    log.info("\n🎬 BOOTING RENDER ENGINE...")
    db_manager.init_db()

    # ── 1. Resolve job details ────────────────────────────────────────────────
    if not (video_id and title and artist):
        job = _get_ready_job()   # Bug 5 fix: uses public function
        if not job:
            log.info("💤 No ASSETS_READY songs. Nothing to render.")
            return False
        video_id, title, artist = job
        workspace = None

    log.info("🚀 Rendering: %s — %s  (ID: %s)", title, artist, video_id)

    # ── 2. Locate asset folder ────────────────────────────────────────────────
    asset_folder = _find_asset_folder(workspace, title)
    if not asset_folder:
        log.error("❌ Asset folder not found for: %s", title)
        return False
    log.info("   📂 Asset folder: %s", asset_folder)

    # ── 3. Validate required files ────────────────────────────────────────────
    metadata_path   = os.path.join(asset_folder, "metadata.json")
    timestamps_path = os.path.join(asset_folder, "timestamps.json")
    audio_path      = os.path.join(asset_folder, "audio.mp3")

    missing = [p for p in (metadata_path, timestamps_path, audio_path) if not os.path.exists(p)]
    if missing:
        for m in missing:
            log.error("   ❌ Missing: %s", m)
        return False

    # ── 4. Load metadata ──────────────────────────────────────────────────────
    try:
        with open(metadata_path, "r", encoding="utf-8") as fh:
            meta = json.load(fh)
    except (json.JSONDecodeError, OSError) as exc:
        log.error("❌ Could not read metadata.json: %s", exc)
        return False

    rank = int(meta.get("rank", 0))

    # ── 5. Select background (Feature 7: honours pinned_bg setting) ───────────
    bg_source = _select_background(rank)
    bg_index  = (max(0, rank - 1) % NUM_BACKGROUNDS) + 1
    if "pinned" in bg_source:
        log.info("   🖼️  Background: pinned custom image")
    else:
        log.info("   🖼️  Background: %d.jpg  (rank %d)", bg_index, rank)

    if not os.path.exists(bg_source):
        log.error("❌ Background image not found: %s", bg_source)
        return False

    # ── 6. Compute audio delay ────────────────────────────────────────────────
    audio_delay = _compute_audio_delay(timestamps_path)
    first_lyric = _first_lyric_start(timestamps_path)
    if audio_delay > 0:
        log.info("   ⏱️  First lyric at %.2fs → audio delayed %.3fs", first_lyric, audio_delay)
    else:
        log.info("   ⏱️  First lyric at %.2fs ≥ 5s → no delay needed", first_lyric)

    # ── 7. Stage core assets ──────────────────────────────────────────────────
    os.makedirs(REACT_PUBLIC_DIR, exist_ok=True)
    log.info("\n   📦 Staging assets → video-engine/public/...")

    for dest_name, src in {
        "audio.mp3":       audio_path,
        "timestamps.json": timestamps_path,
        "metadata.json":   metadata_path,
    }.items():
        shutil.copy(src, os.path.join(REACT_PUBLIC_DIR, dest_name))
        log.info("   ✅ %s", dest_name)

    shutil.copy(bg_source, os.path.join(REACT_PUBLIC_DIR, "bg.jpg"))
    log.info("   ✅ bg.jpg")

    if os.path.exists(LOGO_PATH):
        shutil.copy(LOGO_PATH, os.path.join(REACT_PUBLIC_DIR, "logo.png"))
        log.info("   ✅ logo.png")
    else:
        log.warning("   ⚠️  logo.png not found — rendering without logo.")

    with open(os.path.join(REACT_PUBLIC_DIR, "audioConfig.json"), "w") as fh:
        json.dump({"audioDelayInVideo": audio_delay}, fh, indent=2)
    log.info("   ✅ audioConfig.json  (delay=%.3fs)", audio_delay)

    # ── 8. Stage fonts + write fontConfig.json ────────────────────────────────
    log.info("\n   🔤 Staging fonts...")
    font_config = _stage_fonts()
    with open(os.path.join(REACT_PUBLIC_DIR, "fontConfig.json"), "w") as fh:
        json.dump(font_config, fh, indent=2)
    log.info("   ✅ fontConfig.json")

    active = [f"{r}={font_config[fk]}" for r, fk in
              [("title","titleFontFile"),("artist","artistFontFile"),("lyrics","lyricsFontFile")]
              if font_config[fk]]
    log.info("   🔤 Active fonts: %s", ", ".join(active) if active else "none (using Inter fallback)")

    # ── 9. Run Remotion renderer ──────────────────────────────────────────────
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    today      = datetime.now().strftime("%Y-%m-%d")
    safe_title = _clean_name(title)
    out_path   = os.path.abspath(os.path.join(OUTPUT_DIR, f"{today}-{safe_title}.mp4"))

    log.info("\n   🎞️  Rendering → %s", out_path)
    log.info("   (This may take several minutes...)\n")

    use_shell = os.name == "nt"
    try:
        subprocess.run(
            ["npx", "remotion", "render", "EchoForgeLyricVideo", out_path],
            cwd=VIDEO_ENGINE_DIR, check=True, shell=use_shell,
        )
        log.info("\n✅ Render complete! → %s", out_path)
        db_manager.update_song_status(video_id, "VIDEO_CREATED")
        return True
    except subprocess.CalledProcessError as exc:
        log.error("\n❌ Remotion failed (exit code %d).", exc.returncode)
        return False
    except Exception as exc:
        log.error("\n❌ Unexpected render error: %s", exc)
        return False


# ─── CLI ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="EchoForge Render Engine")
    parser.add_argument("--video-id",  default=None)
    parser.add_argument("--title",     default=None)
    parser.add_argument("--artist",    default=None)
    parser.add_argument("--workspace", default=None)
    args = parser.parse_args()

    ok = render_video(
        video_id=args.video_id, title=args.title,
        artist=args.artist,     workspace=args.workspace,
    )
    print("\nRender:", "SUCCESS" if ok else "FAILED")