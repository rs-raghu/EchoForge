"""
orchestrator.py

Decoupled EchoForge pipeline orchestrator — fully independent of Telegram.

Changes
───────
• Bug 1  : Fixed inverted "Sync skipped" notify logic using a _sync_ran flag.
• Bug 6  : Guarded workspace None-check before glob in thumbnail fallback.
• Feature 3 : cleanup_workspace() deletes heavy intermediate files after upload.
• Feature 5 : Sync quality score (word match %) is computed after Whisper
              alignment and returned alongside the LYRICS_PREVIEW_READY signal
              so the bot can display it to the user.

CLI USAGE:
    python orchestrator.py --metadata path/to/metadata.json --workspace path/to/folder
    python orchestrator.py --metadata ... --workspace ... --phase upload --video out.mp4
"""

import argparse
import glob
import json
import os
import re
import shutil
import threading
from typing import Callable, Optional

import db_manager
import lyrics_fetcher
import lyrics_sync
import render_engine
import song_fetch
import thumbnail_generation
import youtube_uploader
from config import DISK_MIN_AUDIO_GB, DISK_MIN_DEMUCS_GB, DISK_MIN_RENDER_GB, OUTPUT_DIR
from logger import get_logger
from song_fetch import UNAVAILABLE
from timestamp_processor import process_timestamps

log = get_logger(__name__)

PHASES = ["Audio", "Lyrics", "Sync", "Render", "Thumbnail", "Upload"]
ChecklistCallback = Callable[[str, str], None]

# Files kept after upload; everything else in the workspace is deleted.
_KEEP_AFTER_UPLOAD = {"metadata.json", "lyrics.lrc", "lyrics_clean.lrc",
                      "lyrics.txt", "lyrics_clean.txt", "thumbnail.jpg"}


# ─── Disk-space guard ─────────────────────────────────────────────────────────

def _check_disk(path: str, min_gb: float, phase: str) -> bool:
    try:
        check = path
        while check and not os.path.exists(check):
            parent = os.path.dirname(check)
            if parent == check:
                check = "."
                break
            check = parent
        usage = shutil.disk_usage(check or ".")
        free  = usage.free / (1024 ** 3)
        if free < min_gb:
            log.error("❌ LOW DISK before %s: %.1f GB free, need %.1f GB.", phase, free, min_gb)
            return False
        log.info("💾 Disk OK for %s: %.1f GB free (need %.1f GB).", phase, free, min_gb)
        return True
    except Exception as exc:
        log.warning("⚠️  Disk check skipped for %s (non-fatal): %s", phase, exc)
        return True


# ─── Feature 5: sync quality score ───────────────────────────────────────────

def _compute_sync_quality(workspace: str) -> float | None:
    """
    Read timestamps.json and compute the fraction of lyric lines that were
    matched by Whisper rather than estimated.

    Returns a float in [0.0, 1.0], or None if the file cannot be read.
    A line is considered Whisper-matched if it has a non-empty 'words' list.
    """
    ts_path = os.path.join(workspace, "timestamps.json")
    if not os.path.exists(ts_path):
        return None
    try:
        with open(ts_path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        segments = data.get("segments", [])
        if not segments:
            return None
        matched = sum(1 for s in segments if s.get("words"))
        return round(matched / len(segments), 3)
    except Exception as exc:
        log.debug("sync quality read failed (non-fatal): %s", exc)
        return None


# ─── Feature 3: workspace cleanup ─────────────────────────────────────────────

def cleanup_workspace(workspace: str) -> None:
    """
    Delete heavy intermediate files from the workspace after a successful upload,
    keeping only the small files needed for future reference.

    Files deleted: audio.mp3, vocals.mp3, timestamps_raw.json, any demucs stems.
    Files kept   : metadata.json, lyrics.lrc, lyrics_clean.lrc, lyrics.txt,
                   lyrics_clean.txt, thumbnail.jpg, timestamps.json.

    Controlled by CLEANUP_AFTER_UPLOAD=true in .env (default: false).
    """
    import os as _os
    from dotenv import load_dotenv
    load_dotenv()
    if _os.getenv("CLEANUP_AFTER_UPLOAD", "false").lower() != "true":
        log.debug("Workspace cleanup skipped (CLEANUP_AFTER_UPLOAD not set).")
        return

    if not workspace or not _os.path.isdir(workspace):
        return

    log.info("🧹 Cleaning workspace: %s", workspace)
    deleted = []
    for entry in _os.listdir(workspace):
        if entry in _KEEP_AFTER_UPLOAD:
            continue
        full = _os.path.join(workspace, entry)
        try:
            if _os.path.isfile(full):
                _os.remove(full)
                deleted.append(entry)
            elif _os.path.isdir(full):
                shutil.rmtree(full)
                deleted.append(entry + "/")
        except Exception as exc:
            log.warning("⚠️  Could not delete %s: %s", full, exc)

    if deleted:
        log.info("🗑️  Deleted %d item(s): %s", len(deleted), ", ".join(deleted))
    else:
        log.info("✅ Nothing to clean up.")


# ─── Main pipeline ────────────────────────────────────────────────────────────

def run_pipeline(
    song_data: dict,
    cancel_event: Optional[threading.Event] = None,
    checklist_cb: Optional[ChecklistCallback] = None,
):
    """
    Stateful pipeline orchestrator. Resumes from the last completed DB status.

    Return values
    ─────────────
    ("LYRICS_PREVIEW_READY", path, type, quality_score)  — lyrics need approval
    ("PREVIEW_READY", video_path)                         — video needs approval
    True              — fully complete
    False             — unrecoverable failure
    "UNAVAILABLE"     — video is geo/age-blocked or removed
    "NEEDS_MANUAL_LYRICS" — all lyric sources exhausted
    "CANCELLED"       — cancel_event was set between phases
    "LOW_DISK"        — not enough free space
    """
    def _notify(phase: str, status: str, reason: str = "") -> None:
        if checklist_cb:
            try:
                # Feature 10: pass optional reason string to the callback
                checklist_cb(phase, status, reason)
            except Exception as cb_err:
                log.debug("checklist_cb error (non-fatal): %s", cb_err)

    def _cancelled() -> bool:
        if cancel_event and cancel_event.is_set():
            log.info("🛑 Pipeline cancelled between phases.")
            return True
        return False

    workspace = song_data.get("workspace_dir")
    title     = song_data.get("title", "Unknown")
    artist    = song_data.get("artist", "Unknown")
    url       = song_data.get("url", "")
    video_id  = song_data.get("video_id", "")

    log.info("⚙️  ORCHESTRATOR START: %s — %s", artist, title)
    log.info("📂 Workspace: %s", workspace)

    for phase in PHASES:
        _notify(phase, "pending")

    try:
        db_manager.init_db()
        current_status = db_manager.get_song_status(video_id)

        if current_status in ("VIDEO_CREATED", "UPLOADED", "COMPLETED", "DISCARDED"):
            log.info("✅ Pipeline already finished (Status: %s).", current_status)
            for phase in PHASES:
                _notify(phase, "skipped")
            return True

        if not current_status:
            db_manager.insert_new_job(video_id, title, artist, "PENDING")
            current_status = "PENDING"
        else:
            log.info("[*] Resuming from: %s", current_status)

        # ── Bug 1 fix: use a flag to track whether sync ran ───────────────────
        _sync_ran = False

        # ══════════════════════════════════════════════════════════════════════
        # PHASE 1 — AUDIO DOWNLOAD
        # ══════════════════════════════════════════════════════════════════════
        if current_status == "PENDING":
            _notify("Audio", "running")
            if not _check_disk(workspace, DISK_MIN_AUDIO_GB, "audio download"):
                _notify("Audio", "error", "Low disk space")
                return "LOW_DISK"

            audio_path = song_fetch.download_audio(url, workspace)

            if audio_path == UNAVAILABLE:
                _notify("Audio", "error", "Video unavailable")
                db_manager.update_song_status(video_id, "UNAVAILABLE")
                return "UNAVAILABLE"

            if not audio_path:
                _notify("Audio", "error", "Download failed")
                return False

            _notify("Audio", "done")
            db_manager.update_song_status(video_id, "AUDIO_FETCHED")
            current_status = "AUDIO_FETCHED"
        else:
            _notify("Audio", "skipped")

        if _cancelled():
            return "CANCELLED"

        # ══════════════════════════════════════════════════════════════════════
        # PHASE 2 — LYRICS FETCH + LLM FORMAT
        # ══════════════════════════════════════════════════════════════════════
        if current_status == "AUDIO_FETCHED":
            _notify("Lyrics", "running")
            lyric_status, lyric_path = lyrics_fetcher.fetch_lyrics(title, artist, workspace)

            if lyric_status == "SYNCED":
                _notify("Lyrics", "done")
                db_manager.update_song_status(video_id, "LYRICS_READY")
                # Feature 5: no Whisper score yet for pre-synced LRC
                return ("LYRICS_PREVIEW_READY", lyric_path, "SYNCED", None)

            elif lyric_status == "PLAIN":
                _notify("Lyrics", "done")
                db_manager.update_song_status(video_id, "LYRICS_FETCHED")
                return ("LYRICS_PREVIEW_READY", lyric_path, "PLAIN", None)

            else:
                _notify("Lyrics", "error", "All sources exhausted")
                return "NEEDS_MANUAL_LYRICS"
        else:
            _notify("Lyrics", "skipped")

        if _cancelled():
            return "CANCELLED"

        # ══════════════════════════════════════════════════════════════════════
        # PHASE 2.5 — SYNC ENGINE (plain text / manual .txt resume)
        # ══════════════════════════════════════════════════════════════════════
        if current_status == "LYRICS_FETCHED":
            _notify("Sync", "running")
            if not _check_disk(workspace, DISK_MIN_DEMUCS_GB, "Demucs + Whisper"):
                _notify("Sync", "error", "Low disk space")
                return "LOW_DISK"

            audio_file = os.path.join(workspace, "audio.mp3")
            txt_file   = os.path.join(workspace, "lyrics.txt")

            synced_path = lyrics_sync.sync_lyrics(audio_file, txt_file, workspace)
            if not synced_path:
                _notify("Sync", "error", "Demucs/Whisper failed")
                return "NEEDS_MANUAL_LYRICS"

            process_timestamps(workspace)

            # Feature 5: compute and store the sync quality score
            quality = _compute_sync_quality(workspace)
            if quality is not None:
                song_data["sync_quality"] = quality
                log.info("🎯 Sync quality: %.0f%%", quality * 100)

            _notify("Sync", "done")
            _sync_ran = True
            db_manager.update_song_status(video_id, "ASSETS_READY")
            current_status = "ASSETS_READY"

        # ══════════════════════════════════════════════════════════════════════
        # PHASE 2.6 — TIMESTAMPS (pre-synced LRC / manual .lrc resume)
        # ══════════════════════════════════════════════════════════════════════
        if current_status == "LYRICS_READY":
            _notify("Sync", "running")
            ts_path = process_timestamps(workspace)
            if ts_path:
                log.info("✅ timestamps.json ready: %s", ts_path)
            else:
                log.warning("⚠️  Timestamp processing failed — renderer will use LRC fallback.")
            _notify("Sync", "done")
            _sync_ran = True
            db_manager.update_song_status(video_id, "ASSETS_READY")
            current_status = "ASSETS_READY"

        # Bug 1 fix: only notify skipped when sync genuinely didn't run
        if not _sync_ran and current_status not in ("ASSETS_READY", "VIDEO_CREATED"):
            _notify("Sync", "skipped")

        if _cancelled():
            return "CANCELLED"

        # ══════════════════════════════════════════════════════════════════════
        # PHASE 3 — RENDER VIDEO
        # ══════════════════════════════════════════════════════════════════════
        if current_status == "ASSETS_READY":
            _notify("Render", "running")
            if not _check_disk(OUTPUT_DIR, DISK_MIN_RENDER_GB, "video render"):
                _notify("Render", "error", "Low disk space")
                return "LOW_DISK"

            success = render_engine.render_video(
                video_id=video_id, title=title, artist=artist, workspace=workspace,
            )
            if not success:
                _notify("Render", "error", "Remotion render failed")
                return False

            _notify("Render", "done")
            current_status = "VIDEO_CREATED"
        else:
            _notify("Render", "skipped")

        if _cancelled():
            return "CANCELLED"

        # ══════════════════════════════════════════════════════════════════════
        # PHASE 4 — THUMBNAIL + VIDEO PREVIEW PAUSE
        # ══════════════════════════════════════════════════════════════════════
        if current_status == "VIDEO_CREATED":
            safe_title = re.sub(r'[\\/*?:"<>|]', "", title).strip()
            matches    = glob.glob(os.path.join(OUTPUT_DIR, f"*-{safe_title}.mp4"))
            if not matches:
                log.error("❌ No rendered video found for '%s'.", title)
                return False

            video_path = max(matches, key=os.path.getmtime)
            log.info("🎬 Render confirmed: %s", video_path)

            _notify("Thumbnail", "running")
            try:
                from config import REACT_PUBLIC_DIR
                bg_path = os.path.join(REACT_PUBLIC_DIR, "bg.jpg")

                # Bug 6 fix: guard workspace before glob
                if not os.path.exists(bg_path):
                    if workspace and os.path.isdir(workspace):
                        jpgs    = glob.glob(os.path.join(workspace, "*.jpg"))
                        bg_path = jpgs[0] if jpgs else None
                    else:
                        bg_path = None

                thumb_path = thumbnail_generation.generate_thumbnail(
                    title=title, artist=artist,
                    bg_path=bg_path, output_dir=workspace,
                )
                song_data["thumbnail_path"] = thumb_path
                log.info("✅ Thumbnail: %s", thumb_path)
                _notify("Thumbnail", "done")
            except Exception as thumb_err:
                log.warning("⚠️  Thumbnail failed (non-fatal): %s", thumb_err)
                _notify("Thumbnail", "error", str(thumb_err)[:60])
                song_data["thumbnail_path"] = None

            return ("PREVIEW_READY", video_path)

        log.info("🎉 Orchestrator complete for '%s'.", title)
        return True

    except Exception as exc:
        log.exception("❌ Orchestrator crashed: %s", exc)
        return False


# ─── Upload-only (called after video preview is approved) ─────────────────────

def run_upload_only(song_data: dict, video_path: str) -> bool:
    """
    Upload phase only. Calls cleanup_workspace() on success if configured.
    """
    title      = song_data.get("title", "unknown")
    video_id   = song_data.get("video_id")
    thumb_path = song_data.get("thumbnail_path")
    workspace  = song_data.get("workspace_dir")

    log.info("📤 UPLOAD PHASE: %s", title)
    try:
        if not os.path.exists(video_path):
            log.error("❌ Video file not found: %s", video_path)
            return False

        yt_id = youtube_uploader.upload_video(
            video_path=video_path,
            song_data=song_data,
            thumbnail_path=thumb_path,
        )

        if yt_id:
            db_manager.update_song_status(video_id, "UPLOADED")
            log.info("🎉 Uploaded! '%s' → https://youtu.be/%s", title, yt_id)
            # Feature 3: clean up workspace after upload
            if workspace:
                cleanup_workspace(workspace)
            return True

        log.error("❌ Upload failed.")
        return False

    except Exception as exc:
        log.exception("❌ run_upload_only crashed: %s", exc)
        return False


# ─── CLI ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="EchoForge Pipeline Orchestrator")
    parser.add_argument("--metadata",  required=True, help="Path to metadata.json")
    parser.add_argument("--workspace", required=True, help="Path to workspace folder")
    parser.add_argument("--phase",     choices=["full", "upload"], default="full")
    parser.add_argument("--video",     default=None,
                        help="(upload mode) Path to rendered .mp4")
    args = parser.parse_args()

    with open(args.metadata, "r", encoding="utf-8") as fh:
        song = json.load(fh)
    song["workspace_dir"] = args.workspace

    def _cli_cb(phase: str, status: str, reason: str = "") -> None:
        icons = {"pending": "⬜", "running": "⏳", "done": "✅",
                 "error": "❌", "skipped": "⏭️"}
        suffix = f" — {reason}" if reason else ""
        print(f"  {icons.get(status,'?')} {phase}: {status}{suffix}")

    if args.phase == "upload":
        if not args.video:
            parser.error("--video is required in upload mode.")
        ok = run_upload_only(song, args.video)
        print("\nUpload:", "SUCCESS" if ok else "FAILED")
    else:
        res = run_pipeline(song, checklist_cb=_cli_cb)
        print(f"\nResult: {res}")