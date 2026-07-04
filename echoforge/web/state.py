"""State labels and progress rules for the Web Studio shell."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class StateMeta:
    raw: str
    studio_state: str
    label: str
    tone: str
    progress: int
    next_action: str


STATE_META: dict[str, StateMeta] = {
    "DISCOVERED": StateMeta("DISCOVERED", "DISCOVERED", "Discovered", "neutral", 5, "Add to queue"),
    "STAGED": StateMeta("STAGED", "AUDIO_PENDING", "Ready to process", "review", 12, "Run pipeline"),
    "AUDIO_FETCHED": StateMeta("AUDIO_FETCHED", "AUDIO_READY", "Audio ready", "processing", 25, "Fetch lyrics"),
    "LYRICS_REVIEW_PENDING": StateMeta(
        "LYRICS_REVIEW_PENDING",
        "LYRICS_REVIEW",
        "Lyrics review",
        "warning",
        38,
        "Approve lyrics",
    ),
    "LYRICS_APPROVED": StateMeta("LYRICS_APPROVED", "SYNC_PENDING", "Sync pending", "processing", 50, "Run auto-sync"),
    "ASSETS_READY": StateMeta("ASSETS_READY", "SYNC_APPROVED", "Sync ready", "success", 68, "Render preview"),
    "PREVIEW_PENDING": StateMeta("PREVIEW_PENDING", "PREVIEW_READY", "Preview ready", "review", 82, "Approve upload"),
    "VIDEO_APPROVED": StateMeta("VIDEO_APPROVED", "UPLOAD_PENDING", "Upload pending", "processing", 92, "Upload"),
    "PUBLISHED": StateMeta("PUBLISHED", "PUBLISHED", "Published", "success", 100, "Open published URL"),
    "PAUSED": StateMeta("PAUSED", "PAUSED", "Paused", "neutral", 45, "Resume"),
    "FAILED": StateMeta("FAILED", "FAILED", "Failed", "danger", 45, "Retry"),
    "DISCARDED": StateMeta("DISCARDED", "DISCARDED", "Discarded", "muted", 0, "Restore later"),
    "UNAVAILABLE": StateMeta("UNAVAILABLE", "FAILED", "Unavailable", "danger", 0, "Choose another source"),
    "EDITING_REQUIRED": StateMeta(
        "EDITING_REQUIRED",
        "FINAL_READY",
        "External edit pending",
        "review",
        86,
        "Check edited export",
    ),
}


CHECKLIST = (
    ("audio", "Audio downloaded"),
    ("lyrics", "Lyrics fetched"),
    ("lyricsApproved", "Lyrics approved"),
    ("timestamps", "Timing generated"),
    ("syncApproved", "Sync approved"),
    ("design", "Design selected"),
    ("preview", "Preview rendered"),
    ("final", "Final rendered"),
    ("uploaded", "Uploaded"),
)


def get_state_meta(raw_state: str) -> StateMeta:
    """Return display metadata for a legacy or Web Studio state."""
    return STATE_META.get(
        raw_state,
        StateMeta(raw_state, raw_state, raw_state.replace("_", " ").title(), "neutral", 0, "Review"),
    )


def action_key_for_state(raw_state: str, target_state: str | None = None) -> str | None:
    """Return the primary action key the frontend can call for a project."""
    if raw_state == "DISCOVERED":
        return "stage"
    if raw_state in {"STAGED", "PAUSED"}:
        return "run_full"
    if raw_state == "AUDIO_FETCHED":
        return "fetch_lyrics"
    if raw_state == "LYRICS_REVIEW_PENDING":
        return "approve_lyrics"
    if raw_state == "LYRICS_APPROVED":
        return "assets_only"
    if raw_state == "ASSETS_READY":
        return "render_preview" if target_state == "ASSETS_READY" else "continue_video"
    if raw_state == "PREVIEW_PENDING":
        return "render_final"
    if raw_state == "VIDEO_APPROVED":
        return "upload_youtube"
    if raw_state == "FAILED":
        return "retry"
    return None
