"""
auto_discovery.py

Discovers the next processable song from YouTube's weekly charts.

Changes
───────
• Bug 8   : get_top_song() now calls db_manager.get_statuses_for_ids() —
            one batch SQL query instead of N individual lock acquisitions.
• Feature 4: Duplicate detection — before returning a winner, checks whether
             a song with the same (normalised) title+artist was already
             processed under a different video_id and skips it if so.
"""

import json
import os
import re
from datetime import datetime, timedelta, timezone

import db_manager
from config import ASSETS_DIR
from logger import get_logger

log = get_logger(__name__)

_CHART_REFRESH_UTC_HOUR = 20   # 12:00 PM PST = 20:00 UTC (conservative, DST-safe)


# ─── Helpers ──────────────────────────────────────────────────────────────────

def clean_folder_name(name: str) -> str:
    return re.sub(r'[\\/*?:"<>|]', "", name).strip()


def _most_recent_chart_refresh() -> datetime:
    """Return the most recent Sunday at _CHART_REFRESH_UTC_HOUR UTC."""
    now              = datetime.now(timezone.utc)
    days_since_sunday = now.weekday() + 1
    if days_since_sunday == 7:
        days_since_sunday = 0
    last_sunday = now - timedelta(days=days_since_sunday)
    refresh     = last_sunday.replace(
        hour=_CHART_REFRESH_UTC_HOUR, minute=0, second=0, microsecond=0
    )
    if refresh > now:
        refresh -= timedelta(weeks=1)
    return refresh


def is_cache_stale(scraped_at_str: str | None) -> bool:
    if not scraped_at_str:
        return True
    try:
        scraped_at = datetime.strptime(scraped_at_str, "%Y-%m-%d %H:%M:%S")
        scraped_at = scraped_at.replace(tzinfo=timezone.utc)
    except ValueError:
        log.warning("⚠️  Cannot parse scraped_at '%s' — treating as stale.", scraped_at_str)
        return True
    boundary = _most_recent_chart_refresh()
    stale    = scraped_at < boundary
    if stale:
        log.info("📅 Cache stale: scraped %s UTC, boundary %s UTC.",
                 scraped_at.strftime("%Y-%m-%d %H:%M"),
                 boundary.strftime("%Y-%m-%d %H:%M"))
    else:
        log.info("📅 Cache fresh: scraped %s UTC (boundary %s UTC).",
                 scraped_at.strftime("%Y-%m-%d %H:%M"),
                 boundary.strftime("%Y-%m-%d %H:%M"))
    return stale


def _live_scrape() -> list:
    try:
        from yt_scrapper import scrape_top_50
        songs = scrape_top_50()
        if songs:
            db_manager.cache_charts(songs)
            log.info("✅ Live scrape complete — %d songs cached.", len(songs))
        return songs or []
    except Exception as exc:
        log.error("❌ Live scrape failed: %s", exc)
        return []


def _get_all_charts() -> list:
    db_manager.init_db()
    cached_songs, scraped_at = db_manager.get_cached_charts()
    if cached_songs and not is_cache_stale(scraped_at):
        log.info("⚡ Using cached chart data (%d songs).", len(cached_songs))
        return cached_songs

    log.info("🌐 Cache stale or empty — running live scrape...")
    songs = _live_scrape()
    if not songs:
        if cached_songs:
            log.warning("⚠️  Live scrape failed; using stale cache (%d songs).", len(cached_songs))
            return cached_songs
        log.error("❌ No chart data available.")
        return []
    return songs


# ─── Workspace creation ───────────────────────────────────────────────────────

def create_workspace(song_data: dict, suffix: str = "") -> str:
    today     = datetime.now().strftime("%Y-%m-%d")
    safe_name = clean_folder_name(song_data["title"])
    folder    = f"{today}-{safe_name}" + (f"-{suffix}" if suffix else "")
    workspace = os.path.join(ASSETS_DIR, folder)
    os.makedirs(workspace, exist_ok=True)
    log.info("✅ Workspace: %s", workspace)

    meta_path = os.path.join(workspace, "metadata.json")
    with open(meta_path, "w", encoding="utf-8") as fh:
        json.dump(song_data, fh, indent=4, ensure_ascii=False)
    log.info("📄 metadata.json → %s", meta_path)
    return workspace


# ─── Main public API ──────────────────────────────────────────────────────────

_ACTIVE_STATUSES = {
    "AUDIO_FETCHED", "LYRICS_FETCHED", "LYRICS_READY",
    "ASSETS_READY", "VIDEO_CREATED", "UPLOADED", "UNAVAILABLE", "DISCARDED",
}


def get_top_song(skip_count: int = 0) -> dict | None:
    """
    Return the skip_count-th unprocessed song from the chart.

    Bug 8 fix: all status lookups now happen in ONE batch DB query instead of
    N individual calls, making filtering 100 songs ~100x faster.

    Feature 4: additionally skips any song whose (title, artist) pair already
    exists in pipeline_jobs under a different video_id — prevents re-processing
    the same track that appeared in the charts as a different upload.
    """
    log.info("🚀 ECHOFORGE DISCOVERY  (skip_count=%d)", skip_count)

    all_songs = _get_all_charts()
    if not all_songs:
        log.error("❌ No songs available from charts or cache.")
        return None

    # Bug 8 fix — single batch query for all video IDs
    all_ids      = [s["video_id"] for s in all_songs]
    status_map   = db_manager.get_statuses_for_ids(all_ids)
    log.info("🔍 Filtering %d chart songs against DB (batch query)...", len(all_songs))

    valid = []
    for song in all_songs:
        vid_status = status_map.get(song["video_id"])

        # Skip if video_id is already in an active pipeline state
        if vid_status in _ACTIVE_STATUSES:
            continue

        # Feature 4 — skip if same title+artist was already processed under
        # a different video_id (e.g., official lyric video vs. audio upload)
        dup = db_manager.check_duplicate_title_artist(song["title"], song["artist"])
        if dup and dup["status"] in _ACTIVE_STATUSES:
            log.info(
                "   ⏭️  Duplicate skipped: '%s' already exists as %s (status: %s).",
                song["title"], dup["video_id"], dup["status"],
            )
            continue

        valid.append(song)

    log.info("   → %d valid (unprocessed) songs found.", len(valid))

    if skip_count >= len(valid):
        log.warning("⚠️  No more valid songs at skip index %d.", skip_count)
        return None

    winner = valid[skip_count]
    log.info("🏆 SELECTED: #%d — %s by %s",
             winner.get("rank", "?"), winner["title"], winner["artist"])
    return winner


# ─── Feature 6: /queue support ────────────────────────────────────────────────

def get_queue(max_songs: int = 10) -> list[dict]:
    """
    Return up to max_songs unprocessed songs from the chart (starting at rank 1),
    annotated with their current DB status.  Used by the /queue command to let
    the user see and pick from the full pending list without skipping one-by-one.

    Each entry is a dict with keys: rank, title, artist, video_id, url,
    weekly_views, db_status (None if not yet in DB).
    """
    all_songs  = _get_all_charts()
    if not all_songs:
        return []

    all_ids    = [s["video_id"] for s in all_songs]
    status_map = db_manager.get_statuses_for_ids(all_ids)

    result = []
    for song in all_songs:
        if len(result) >= max_songs:
            break
        vid_status = status_map.get(song["video_id"])
        if vid_status in _ACTIVE_STATUSES:
            continue
        dup = db_manager.check_duplicate_title_artist(song["title"], song["artist"])
        if dup and dup["status"] in _ACTIVE_STATUSES:
            continue
        result.append({**song, "db_status": vid_status})

    return result