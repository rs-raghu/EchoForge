from __future__ import annotations
from datetime import datetime, timezone
from pathlib import Path
from echoforge.core.storage import update_json


def mark_uploaded(project: Path, result: dict):
    if not result.get("ok") or not result.get("video_id"):
        raise ValueError("A successful remote video ID is required")
    def mutate(state):
        state.setdefault("source_youtube_url", state.get("youtube_url"))
        state.update(status="uploaded", current_stage="uploaded", youtube_video_id=result["video_id"],
                     uploaded_youtube_url=result.get("url"), uploaded_at=result.get("uploaded_at"),
                     updated_at=datetime.now(timezone.utc).isoformat())
        state.setdefault("stages", {}).update(renderer="done", tubeharbor="done", uploaded=True)
        return state.copy()
    state = update_json(project / "project_state.json", mutate, {})
    if state.get("song_id"):
        from echoforge.stages.songscout.database import mark_song_status
        mark_song_status(state["song_id"], "used", project_dir=str(project), note="YouTube upload completed")
    return state
