import time
import multiprocessing
import os
import sys

# Ensure the root directory is in the Python path so we can import our modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import db_manager
from utils.logger import get_logger

# Import the isolated workers (we will build these files next!)
try:
    from engine.workers import fetch_audio
    from engine.workers import fetch_lyrics
    from engine.workers import ai_sync
    from engine.workers import render_video
    from engine.workers import youtube_upload
except ImportError as e:
    print(f"⚠️ Warning: Worker modules not fully built yet. ({e})")
    fetch_audio = fetch_lyrics = ai_sync = render_video = youtube_upload = None

log = get_logger(__name__)

# --- WORKER WRAPPERS ---
# We wrap the functions so they can be run securely in isolated processes.

def run_audio_fetch(song):
    log.info(f"🎧 [WORKER] Fetching audio for {song['title']}...")
    if not fetch_audio: return False
    return fetch_audio.download(song)

def run_lyrics_fetch(song):
    log.info(f"📝 [WORKER] Fetching lyrics for {song['title']}...")
    if not fetch_lyrics: return False
    return fetch_lyrics.fetch(song)

def run_ai_sync(song):
    log.info(f"🧠 [WORKER] Running AI Sync (Demucs & Whisper) for {song['title']}...")
    if not ai_sync: return False
    return ai_sync.process(song)

def run_render(song):
    log.info(f"🎬 [WORKER] Rendering video for {song['title']}...")
    if not render_video: return False
    return render_video.render(song)

def run_upload(song):
    log.info(f"🚀 [WORKER] Uploading {song['title']} to YouTube...")
    if not youtube_upload: return False
    return youtube_upload.upload(song)

# --- THE STATE MACHINE ROUTER ---
# Maps the current state to the target worker function and the next resting state.

STATE_MACHINE = {
    'STAGED': {
        'worker': run_audio_fetch,
        'next_state': 'AUDIO_FETCHED',
        'micro': 'DOWNLOADING_AUDIO'
    },
    'AUDIO_FETCHED': {
        'worker': run_lyrics_fetch,
        'next_state': 'LYRICS_REVIEW_PENDING', # Force human review pause!
        'micro': 'FETCHING_LYRICS'
    },
    'LYRICS_APPROVED': {
        'worker': run_ai_sync,
        'next_state': 'ASSETS_READY',
        'micro': 'RUNNING_AI_SYNC'
    },
    'ASSETS_READY': {
        'worker': run_render,
        'next_state': 'PREVIEW_PENDING', # Force human review pause!
        'micro': 'RENDERING_VIDEO'
    },
    'VIDEO_APPROVED': {
        'worker': run_upload,
        'next_state': 'PUBLISHED',
        'micro': 'UPLOADING_TO_YOUTUBE'
    }
}

class ProcessManager:
    def __init__(self):
        self.polling_rate = 2 # Check DB every 2 seconds

    def run_forever(self):
        log.info("⚙️ Orchestrator Daemon Started. Watching database for jobs...")
        db_manager.init_db()
        
        while True:
            job = self.get_highest_priority_job()
            
            if job:
                self.process_job(job)
            else:
                time.sleep(self.polling_rate)

    def get_highest_priority_job(self):
        """Finds a job that wants to move forward based on user input."""
        jobs = db_manager.get_active_jobs()
        for job_stub in jobs:
            # Need to get full song data to check target_macro_state
            song = db_manager.get_song(job_stub['video_id'])
            if not song: continue
            
            if song['current_macro_state'] != song['target_macro_state']:
                # Ensure it isn't paused or aborted
                if not db_manager.check_abort(song['video_id']):
                    # Check if the current state has an actionable next step
                    if song['current_macro_state'] in STATE_MACHINE:
                        return song
        return None

    def process_job(self, song):
        video_id = song['video_id']
        current_state = song['current_macro_state']
        
        step_data = STATE_MACHINE.get(current_state)
        if not step_data:
            log.error(f"❌ Unknown state '{current_state}' for {song['title']}")
            return

        target_func = step_data['worker']
        next_macro = step_data['next_state']
        micro_state = step_data['micro']

        log.info(f"▶️ Executing {micro_state} for '{song['title']}'...")
        
        # 0. Ensure workspace folder exists
        workspace = song['workspace_dir']
        if not workspace:
            workspace = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'workspaces', video_id)
            os.makedirs(workspace, exist_ok=True)
            db_manager.update_state(video_id, workspace_dir=workspace)
            song['workspace_dir'] = workspace

        db_manager.update_state(video_id, micro=micro_state)

        # 1. Spawn the isolated process
        worker_process = multiprocessing.Process(target=target_func, args=(song,))
        worker_process.start()

        # 2. THE WATCHER LOOP (The Kill Switch)
        aborted = False
        while worker_process.is_alive():
            if db_manager.check_abort(video_id):
                log.warning(f"🛑 ABORT SIGNAL RECEIVED for {song['title']}! Terminating process...")
                worker_process.terminate()
                worker_process.join() # Wait for it to die cleanly
                aborted = True
                break
            time.sleep(1) # Check the database kill switch every second

        # 3. Handle the outcome
        if aborted:
            # We killed it. Roll back to the safe macro state and pause.
            db_manager.update_state(video_id, macro='PAUSED', micro='IDLE')
            log.info(f"⏸️ '{song['title']}' paused safely.")
            
        elif worker_process.exitcode == 0:
            # It finished successfully! Advance the state.
            db_manager.update_state(video_id, macro=next_macro, micro='IDLE')
            log.info(f"✅ State advanced: {current_state} -> {next_macro}")
            
        else:
            # It crashed (e.g., Python error inside the worker)
            db_manager.update_state(video_id, macro='FAILED', micro='IDLE')
            log.error(f"❌ Worker crashed during {micro_state}! Exit code: {worker_process.exitcode}")

if __name__ == "__main__":
    # Needed for Windows multiprocessing compatibility
    multiprocessing.freeze_support()
    manager = ProcessManager()
    try:
        manager.run_forever()
    except KeyboardInterrupt:
        print("\n🛑 Orchestrator shut down gracefully.")