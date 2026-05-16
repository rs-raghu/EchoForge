"""
engine/orchestrator.py

EchoForge V3 — Process Manager / State Machine Daemon.

Fixes applied
─────────────
• Bug 1 : PREVIEW_PENDING is NOT in STATE_MACHINE (intentional — it waits for
          human approval). The bot sets macro→VIDEO_APPROVED when the user taps
          "Upload". That state IS in STATE_MACHINE and triggers the uploader.
          The old code used set_target alone which never fired the uploader.

• Bug 2 : Worker exit-code semantics. Workers now call sys.exit(0/1) explicitly.
          A Python function returning False still exits with OS code 0, so the
          orchestrator would incorrectly advance the state on failure.

STATE MACHINE
─────────────
  STAGED            → (audio download)   → AUDIO_FETCHED
  AUDIO_FETCHED     → (lyrics fetch)     → LYRICS_REVIEW_PENDING  ← human pause
  LYRICS_APPROVED   → (AI sync)          → ASSETS_READY
  ASSETS_READY      → (render)           → PREVIEW_PENDING         ← human pause
  VIDEO_APPROVED    → (upload)           → PUBLISHED               ← human triggers

Human-pause states (NOT in STATE_MACHINE — orchestrator ignores them):
  LYRICS_REVIEW_PENDING  — bot shows Approve/Edit buttons
  PREVIEW_PENDING        — bot shows Upload/Discard buttons

The bot advances out of pause states by setting current_macro_state directly
(not just target_macro_state).
"""

import multiprocessing
import os
import sys
import time

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import db_manager
from utils.logger import get_logger

log = get_logger(__name__)

# ── Worker imports ─────────────────────────────────────────────────────────────
try:
    from engine.workers import fetch_audio
    from engine.workers import fetch_lyrics
    from engine.workers import ai_sync
    from engine.workers import render_video
    from engine.workers import youtube_upload
except ImportError as exc:
    log.warning("⚠️  Some worker modules not loaded yet: %s", exc)
    fetch_audio = fetch_lyrics = ai_sync = render_video = youtube_upload = None


# ── Worker wrapper functions ───────────────────────────────────────────────────
# Each wrapper is the target of multiprocessing.Process(target=...).
# Workers must call sys.exit(0) for success and sys.exit(1) for failure.
# Returning a value from a Process target does NOT set the exit code.

def _run_audio_fetch(song: dict) -> None:
    ok = fetch_audio.download(song) if fetch_audio else False
    sys.exit(0 if ok else 1)


def _run_lyrics_fetch(song: dict) -> None:
    ok = fetch_lyrics.fetch(song) if fetch_lyrics else False
    sys.exit(0 if ok else 1)


def _run_ai_sync(song: dict) -> None:
    ok = ai_sync.process(song) if ai_sync else False
    sys.exit(0 if ok else 1)


def _run_render(song: dict) -> None:
    ok = render_video.render(song) if render_video else False
    sys.exit(0 if ok else 1)


def _run_upload(song: dict) -> None:
    ok = youtube_upload.upload(song) if youtube_upload else False
    sys.exit(0 if ok else 1)


# ── State machine definition ───────────────────────────────────────────────────
#
# Keys   = macro states the orchestrator can act on.
# Values = what to do and what state to set next.
#
# PAUSE states (LYRICS_REVIEW_PENDING, PREVIEW_PENDING) are deliberately absent.
# The orchestrator must never auto-advance through human checkpoints.

STATE_MACHINE: dict[str, dict] = {
    "STAGED": {
        "worker":     _run_audio_fetch,
        "next_state": "AUDIO_FETCHED",
        "micro":      "DOWNLOADING_AUDIO",
    },
    "AUDIO_FETCHED": {
        "worker":     _run_lyrics_fetch,
        "next_state": "LYRICS_REVIEW_PENDING",   # human pause
        "micro":      "FETCHING_LYRICS",
    },
    "LYRICS_APPROVED": {
        "worker":     _run_ai_sync,
        "next_state": "ASSETS_READY",
        "micro":      "RUNNING_AI_SYNC",
    },
    "ASSETS_READY": {
        "worker":     _run_render,
        "next_state": "PREVIEW_PENDING",          # human pause
        "micro":      "RENDERING_VIDEO",
    },
    # Bug 1 fix: VIDEO_APPROVED is the bot-set state that triggers the uploader.
    # When the user taps "Upload", the bot calls:
    #   db_manager.update_state(video_id, macro='VIDEO_APPROVED')
    #   db_manager.set_target_state(video_id, 'PUBLISHED')
    # The orchestrator then finds VIDEO_APPROVED in STATE_MACHINE and runs upload.
    "VIDEO_APPROVED": {
        "worker":     _run_upload,
        "next_state": "PUBLISHED",
        "micro":      "UPLOADING_TO_YOUTUBE",
    },
}

# States the orchestrator never touches (waiting for human input)
_PAUSE_STATES  = {"LYRICS_REVIEW_PENDING", "PREVIEW_PENDING"}
# Terminal states — job is done, skip forever
_TERMINAL_STATES = {"PUBLISHED", "DISCARDED", "UNAVAILABLE", "PAUSED", "FAILED"}


# ── Process Manager ────────────────────────────────────────────────────────────

class ProcessManager:
    """
    Daemon that polls the DB every `polling_rate` seconds, finds the
    highest-priority actionable job, and runs its worker in an isolated
    subprocess with a real kill switch.
    """

    def __init__(self, polling_rate: float = 2.0):
        self.polling_rate = polling_rate

    # ── Main loop ──────────────────────────────────────────────────────────────

    def run_forever(self) -> None:
        log.info("⚙️  Orchestrator Daemon started — watching DB for jobs...")
        db_manager.init_db()

        while True:
            job = self._get_next_job()
            if job:
                self._process_job(job)
            else:
                time.sleep(self.polling_rate)

    # ── Job selection ──────────────────────────────────────────────────────────

    def _get_next_job(self) -> dict | None:
        """
        Find the first song that:
          1. Has an actionable current_macro_state (in STATE_MACHINE).
          2. Has not yet reached its target_macro_state.
          3. Has no abort_requested flag.
        """
        for stub in db_manager.get_active_jobs():
            song = db_manager.get_song(stub["video_id"])
            if not song:
                continue

            macro  = song["current_macro_state"]
            target = song["target_macro_state"]

            # Skip pause / terminal states
            if macro in _PAUSE_STATES or macro in _TERMINAL_STATES:
                continue

            # Skip if already at target
            if macro == target:
                continue

            # Skip if abort was requested
            if db_manager.check_abort(song["video_id"]):
                continue

            # Only act on states we know how to handle
            if macro in STATE_MACHINE:
                return song

        return None

    # ── Job execution ──────────────────────────────────────────────────────────

    def _process_job(self, song: dict) -> None:
        video_id     = song["video_id"]
        macro        = song["current_macro_state"]
        step         = STATE_MACHINE[macro]

        worker_fn    = step["worker"]
        next_macro   = step["next_state"]
        micro_label  = step["micro"]

        log.info("▶️  [%s] %s  →  running %s", video_id[:8], song["title"], micro_label)

        # ── Ensure workspace exists ───────────────────────────────────────────
        workspace = song.get("workspace_dir")
        if not workspace:
            root      = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            workspace = os.path.join(root, "workspaces", video_id)
            os.makedirs(workspace, exist_ok=True)
            db_manager.update_state(video_id, workspace_dir=workspace)
            song["workspace_dir"] = workspace

        # Store URL on song dict if missing (workers need it)
        if not song.get("url"):
            song["url"] = f"https://www.youtube.com/watch?v={video_id}"

        # ── Update micro state ────────────────────────────────────────────────
        db_manager.update_state(video_id, micro=micro_label)

        # ── Spawn isolated worker process ─────────────────────────────────────
        proc = multiprocessing.Process(target=worker_fn, args=(song,), daemon=False)
        proc.start()

        # ── Watcher loop — checks kill switch every second ────────────────────
        aborted = False
        while proc.is_alive():
            if db_manager.check_abort(video_id):
                log.warning("🛑 Abort signal for '%s' — terminating process.", song["title"])
                proc.terminate()
                proc.join(timeout=10)
                if proc.is_alive():
                    proc.kill()   # SIGKILL if SIGTERM wasn't enough
                aborted = True
                break
            time.sleep(1)

        if not aborted:
            proc.join()   # clean up zombie

        # ── Handle outcome ────────────────────────────────────────────────────
        if aborted:
            db_manager.update_state(video_id, macro="PAUSED", micro="IDLE")
            log.info("⏸️  '%s' paused safely.", song["title"])

        elif proc.exitcode == 0:
            # Bug 2 fix: only advance when exit code is explicitly 0
            db_manager.update_state(video_id, macro=next_macro, micro="IDLE")
            log.info("✅ %s → %s  ('%s')", macro, next_macro, song["title"])

        else:
            db_manager.update_state(video_id, macro="FAILED", micro="IDLE")
            log.error(
                "❌ Worker crashed during %s for '%s' (exit code %s).",
                micro_label, song["title"], proc.exitcode,
            )


# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    multiprocessing.freeze_support()   # required on Windows
    manager = ProcessManager()
    try:
        manager.run_forever()
    except KeyboardInterrupt:
        print("\n🛑 Orchestrator shut down gracefully.")
