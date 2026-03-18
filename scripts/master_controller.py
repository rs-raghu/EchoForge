import os
import re
import threading
import db_manager
import song_fetch
import lyrics_fetcher
import lyrics_sync
import render_engine          # FIX 1a: was missing
import youtube_uploader       # FIX 1b: was missing
from song_fetch import UNAVAILABLE
from timestamp_processor import process_timestamps


def run_pipeline(song_data, cancel_event: threading.Event | None = None):
    """
    Stateful orchestrator. Resumes from the last completed step using the database.

    Status flow:
    PENDING → AUDIO_FETCHED → LYRICS_FETCHED → ASSETS_READY → VIDEO_CREATED → UPLOADED
                            ↘ LYRICS_READY (if SYNCED .lrc) → ASSETS_READY → VIDEO_CREATED → UPLOADED

    cancel_event : optional threading.Event set by the Telegram /cancel command.
      Checked between every phase — the pipeline exits cleanly at the next safe
      boundary rather than being killed mid-subprocess (which could corrupt files).
      The DB status is left at its last completed phase so the pipeline can be
      resumed later with /start.
    """

    def _cancelled() -> bool:
        """Returns True and prints a notice if cancellation was requested."""
        if cancel_event and cancel_event.is_set():
            print(f"\n🛑 Pipeline cancelled by user after completing: {current_status}")
            return True
        return False
    workspace = song_data.get('workspace_dir')
    title     = song_data.get('title')
    artist    = song_data.get('artist')
    url       = song_data.get('url')
    video_id  = song_data.get('video_id')

    print(f"\n⚙️ MASTER CONTROLLER TAKING OVER: {title}")
    print(f"📂 Workspace: {workspace}")

    try:
        db_manager.init_db()
        current_status = db_manager.get_song_status(video_id)

        # FIX 6: Removed ASSETS_READY from this guard so the pipeline
        # can resume into the render phase if it was interrupted there.
        if current_status in ["VIDEO_CREATED", "UPLOADED", "COMPLETED", "DISCARDED"]:
            print(f"✅ Pipeline already finished for '{title}' (Status: {current_status}). Aborting.")
            return True

        # New song
        if not current_status:
            print("\n[+] New song detected. Initializing in Database...")
            db_manager.insert_new_job(video_id, title, artist, status="PENDING")
            current_status = "PENDING"
        else:
            print(f"\n[*] Resuming pipeline from status: {current_status}")

        # ==========================================
        # PHASE 1: AUDIO FETCH
        # ==========================================
        if current_status == "PENDING":
            print("\n[1/4] Triggering Audio Download...")
            audio_path = song_fetch.download_audio(url, workspace)

            if audio_path == UNAVAILABLE:
                db_manager.update_song_status(video_id, "UNAVAILABLE")
                print(f"⛔ Marked as UNAVAILABLE. Signalling Telegram to skip to next song.")
                return "UNAVAILABLE"

            if not audio_path:
                print("❌ Pipeline aborted: Audio download failed.")
                return False

            db_manager.update_song_status(video_id, "AUDIO_FETCHED")
            current_status = "AUDIO_FETCHED"

        if _cancelled():
            return "CANCELLED"

        # ==========================================
        # PHASE 2: LYRICS FETCH
        # ==========================================
        if current_status == "AUDIO_FETCHED":
            print("\n[2/4] Triggering Multi-Tier Lyrics Fetcher...")

            lyric_status, lyric_path = lyrics_fetcher.fetch_lyrics(title, artist, workspace)

            if lyric_status == "SYNCED":
                # Pre-synced .lrc from syncedlyrics — still need timestamps.json
                db_manager.update_song_status(video_id, "LYRICS_READY")
                current_status = "LYRICS_READY"

            elif lyric_status == "PLAIN":
                db_manager.update_song_status(video_id, "LYRICS_FETCHED")
                current_status = "LYRICS_FETCHED"

            else:
                print("❌ Lyrics fetch failed. Telegram intervention required.")
                return "NEEDS_MANUAL_LYRICS"

        if _cancelled():
            return "CANCELLED"

        # ==========================================
        # PHASE 2.5: SYNC ENGINE (PLAIN lyrics only)
        # Handles both: auto PLAIN result and manual .txt upload resume
        # ==========================================
        if current_status == "LYRICS_FETCHED":
            print("\n[2.5/4] Plain text lyrics detected. Running Sync Engine...")
            audio_file = os.path.join(workspace, "audio.mp3")
            txt_file   = os.path.join(workspace, "lyrics.txt")

            synced_path = lyrics_sync.sync_lyrics(audio_file, txt_file, workspace)

            if not synced_path:
                print("❌ Sync Engine failed. Telegram intervention required.")
                return "NEEDS_MANUAL_LYRICS"

            # Run post-processor so filler merging and clean line-level
            # segments are applied — same quality as the SYNCED path.
            print("\n[2.5b/4] Running Timestamp Post-Processor on Whisper output...")
            process_timestamps(workspace)

            db_manager.update_song_status(video_id, "ASSETS_READY")
            current_status = "ASSETS_READY"

        # ==========================================
        # PHASE 2.6: TIMESTAMPS (SYNCED lyrics path)
        # Pre-synced .lrc has timestamps but no word-level data.
        # We convert the LRC directly into timestamps.json so the
        # renderer has what it needs.
        # ==========================================
        if current_status == "LYRICS_READY":
            print("\n[2.6/4] Pre-synced LRC detected. Generating timestamps.json...")
            ts_path = process_timestamps(workspace)

            if not ts_path:
                print("⚠️ Timestamp processing failed. Renderer will attempt LRC fallback.")
            else:
                print(f"✅ timestamps.json ready: {ts_path}")

            db_manager.update_song_status(video_id, "ASSETS_READY")
            current_status = "ASSETS_READY"

        if _cancelled():
            return "CANCELLED"

        # ==========================================
        # PHASE 3: RENDER VIDEO
        # ==========================================
        if current_status == "ASSETS_READY":
            print("\n[3/4] Assets confirmed. Handing off to Render Engine...")

            # Pass all job details directly so the render engine never has to
            # do a DB query and can never accidentally pick up a different song.
            success = render_engine.render_video(
                video_id  = video_id,
                title     = title,
                artist    = artist,
                workspace = workspace,
            )

            if not success:
                print(f"❌ Render Engine failed for '{title}'. Check logs above.")
                return False

            current_status = "VIDEO_CREATED"

        if _cancelled():
            return "CANCELLED"

        # ==========================================
        # PHASE 4: VIDEO PREVIEW (pause for Telegram approval)
        # ==========================================
        # Instead of auto-uploading, we surface the rendered video to the
        # user for review.  The bot sends a compressed preview clip with
        # Upload / Discard buttons.  run_upload_only() handles Phase 4 proper
        # after the user approves.
        if current_status == "VIDEO_CREATED":
            import glob
            safe_title       = re.sub(r'[\\/*?:"<>|]', "", title).strip()
            output_dir       = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "Output"))
            matches          = glob.glob(os.path.join(output_dir, f"*-{safe_title}.mp4"))

            if not matches:
                print(f"❌ Pipeline aborted: no rendered video found in Output/ for '{title}'")
                return False

            final_video_path = max(matches, key=os.path.getmtime)
            print(f"   🎬 Render confirmed: {final_video_path}")
            print("   ⏸️  Pausing for Telegram preview approval...")
            return ("PREVIEW_READY", final_video_path)

        print(f"\n🎉 Master Controller complete! '{title}' → Status: {current_status}")
        return True

    except Exception as e:
        print(f"❌ Master Controller crashed: {e}")
        import traceback
        traceback.print_exc()
        return False

def run_upload_only(song_data: dict, video_path: str) -> bool:
    """
    Phase 4 standalone — uploads an already-rendered video to YouTube.

    Called by the Telegram bot after the user approves the preview clip.
    Finds no files, runs no subprocesses — just calls the uploader and
    updates the DB.

    Returns True on success, False on failure.
    """
    title    = song_data.get("title", "unknown")
    video_id = song_data.get("video_id")

    print(f"\n📤 UPLOAD PHASE: {title}")
    print(f"   🎬 Video path: {video_path}")

    try:
        if not os.path.exists(video_path):
            print(f"❌ Upload aborted: video file not found at {video_path}")
            return False

        yt_video_id = youtube_uploader.upload_video(video_path, song_data)

        if yt_video_id:
            db_manager.update_song_status(video_id, "UPLOADED")
            print(f"\n🎉 Upload complete! \'{title}\' → UPLOADED")
            return True
        else:
            print("❌ Upload failed. Check youtube_uploader logs above.")
            return False

    except Exception as e:
        print(f"❌ run_upload_only crashed: {e}")
        import traceback
        traceback.print_exc()
        return False