import os
import re
import db_manager
import song_fetch
import lyrics_fetcher
import lyrics_sync
import render_engine          # FIX 1a: was missing
import youtube_uploader       # FIX 1b: was missing
from song_fetch import UNAVAILABLE
from timestamp_processor import process_timestamps


def run_pipeline(song_data):
    """
    Stateful orchestrator. Resumes from the last completed step using the database.

    Status flow:
    PENDING → AUDIO_FETCHED → LYRICS_FETCHED → ASSETS_READY → VIDEO_CREATED → UPLOADED
                            ↘ LYRICS_READY (if SYNCED .lrc) → ASSETS_READY → VIDEO_CREATED → UPLOADED
    """
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
        if current_status in ["VIDEO_CREATED", "UPLOADED", "COMPLETED"]:
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

        # ==========================================
        # PHASE 3: RENDER VIDEO
        # ==========================================
        if current_status == "ASSETS_READY":
            print("\n[3/4] Assets confirmed. Handing off to Render Engine...")

            # FIX 4: render_video() takes no arguments — it fetches the job
            # from the DB itself. Passing kwargs would crash with TypeError.
            success = render_engine.render_video()

            if not success:
                print(f"❌ Render Engine failed for '{title}'. Check logs above.")
                return False

            current_status = "VIDEO_CREATED"

        # ==========================================
        # PHASE 4: YOUTUBE UPLOAD
        # ==========================================
        # FIX 2: return True was here, making this entire block dead code.
        # FIX 3: status was "VIDEO_RENDERED" — render_engine sets "VIDEO_CREATED".
        if current_status == "VIDEO_CREATED":
            print("\n[4/4] Triggering YouTube Uploader...")

            # Find the rendered video by title pattern (not date) so the
            # lookup works even if the render crossed midnight or the pipeline
            # was resumed on a later day.
            import glob
            safe_title = re.sub(r'[\\/*?:"<>|]', "", title).strip()
            output_dir = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "Output"))
            matches    = glob.glob(os.path.join(output_dir, f"*-{safe_title}.mp4"))

            if not matches:
                print(f"❌ Pipeline aborted: no rendered video found in Output/ for '{title}'")
                return False

            # If somehow multiple matches exist, take the most recently modified one
            final_video_path = max(matches, key=os.path.getmtime)
            print(f"   🎬 Found rendered video: {final_video_path}")

            yt_video_id = youtube_uploader.upload_video(final_video_path, song_data)

            if yt_video_id:
                db_manager.update_song_status(video_id, "UPLOADED")
                current_status = "UPLOADED"
            else:
                print("❌ Pipeline aborted: YouTube upload failed.")
                return False

        print(f"\n🎉 Master Controller complete! '{title}' → Status: {current_status}")
        return True

    except Exception as e:
        print(f"❌ Master Controller crashed: {e}")
        import traceback
        traceback.print_exc()
        return False