import os
import db_manager
import song_fetch
import lyrics_fetcher
import lyrics_sync
from song_fetch import UNAVAILABLE
from timestamp_processor import process_timestamps


def run_pipeline(song_data):
    """
    Stateful orchestrator. Resumes from the last completed step using the database.

    Status flow:
    PENDING → AUDIO_FETCHED → LYRICS_FETCHED → LYRICS_SYNCED → ASSETS_READY
                            ↘ LYRICS_READY (if SYNCED .lrc) → ASSETS_READY
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

        # Already finished
        if current_status in ["ASSETS_READY", "VIDEO_CREATED", "UPLOADED", "COMPLETED"]:
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

            if synced_path:
                db_manager.update_song_status(video_id, "ASSETS_READY")
                current_status = "ASSETS_READY"
            else:
                print("❌ Sync Engine failed. Telegram intervention required.")
                return "NEEDS_MANUAL_LYRICS"

        # ==========================================
        # PHASE 2.6: TIMESTAMPS (SYNCED lyrics path)
        # Pre-synced .lrc has timestamps but no word-level data.
        # We convert the LRC directly into timestamps.json so the
        # renderer has what it needs.
        # ==========================================
        if current_status == "LYRICS_READY":
            print("\n[2.6/4] Pre-synced LRC detected. Generating timestamps.json...")
            ts_path = process_timestamps(workspace)
            if ts_path:
                db_manager.update_song_status(video_id, "ASSETS_READY")
                current_status = "ASSETS_READY"
            else:
                print("⚠️ Timestamp processing failed. Check lyrics.lrc content.")
                # Non-fatal: the renderer may still work with LRC alone
                db_manager.update_song_status(video_id, "ASSETS_READY")
                current_status = "ASSETS_READY"

        # ==========================================
        # PHASE 3: IMAGE / BACKGROUND GENERATION
        # ==========================================
        if current_status == "ASSETS_READY":
            print("\n[3/4] Assets ready. Image Engine placeholder — coming next.")
            # image_engine.generate_assets(workspace, metadata)

        print(f"\n🎉 Master Controller reached {current_status} for '{title}'!")
        return True

    except Exception as e:
        print(f"❌ Master Controller crashed: {e}")
        import traceback
        traceback.print_exc()
        return False