"""
discovery/chart_scraper.py

Scrapes the YouTube Music global charts using ytmusicapi (no Selenium/headless
browser required).

Changes from original
─────────────────────
• Each song dict now includes a `url` field so fetch_audio.py never has to
  reconstruct it from video_id alone.
• scrape_top_charts() is a plain synchronous function — asyncio.to_thread()
  in the bot wraps it so the event loop stays unblocked.
• The bot calls db_manager.mark_chart_scraped() after a successful run so
  subsequent calls within CHART_CACHE_HOURS are blocked at the UI level.

CLI USAGE:
    python chart_scraper.py --limit 10
"""

import argparse
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.logger import get_logger

log = get_logger(__name__)

try:
    from ytmusicapi import YTMusic
except ImportError:
    log.error("❌ 'ytmusicapi' not installed. Run: pip install ytmusicapi")
    YTMusic = None


def scrape_top_charts(limit: int = 20, country: str = "US") -> list[dict]:
    """
    Fetch the top *limit* trending songs from YouTube Music charts.

    Returns a list of dicts:
        {
            "video_id": str,
            "title":    str,
            "artist":   str,
            "url":      str,   ← full YouTube watch URL
        }

    Returns an empty list on any failure (caller handles gracefully).
    """
    if not YTMusic:
        raise ImportError("ytmusicapi is not installed.")

    log.info("🔍 Fetching YouTube Music charts (country=%s, limit=%d)...", country, limit)
    yt = YTMusic()

    try:
        charts    = yt.get_charts(country=country)

        # ytmusicapi can return results under 'videos' or 'tracks' depending
        # on the region — try both keys.
        items = (
            charts.get("videos",  {}).get("items", []) or
            charts.get("tracks",  {}).get("items", []) or
            charts.get("trending", {}).get("items", [])
        )

        if not items:
            log.warning("⚠️  ytmusicapi returned no chart items for country=%s", country)
            return []

        songs = []
        for item in items:
            if len(songs) >= limit:
                break

            video_id = item.get("videoId")
            title    = item.get("title")

            # Artists field is a list of {"name": ..., "id": ...} dicts
            artist_list = item.get("artists", [])
            artist      = ", ".join(
                a["name"] for a in artist_list if a.get("name")
            ) or "Unknown Artist"

            if not video_id or not title:
                continue

            songs.append({
                "video_id": video_id,
                "title":    title,
                "artist":   artist,
                "url":      f"https://www.youtube.com/watch?v={video_id}",
            })

        log.info("✅ Scraped %d songs from YouTube Music charts.", len(songs))
        return songs

    except Exception as exc:
        log.error("❌ Chart scrape failed: %s", exc)
        return []


# ── CLI ────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="EchoForge Chart Scraper")
    parser.add_argument("--limit",   type=int, default=10,  help="Number of songs to fetch")
    parser.add_argument("--country", default="US",          help="Country code (default: US)")
    args = parser.parse_args()

    results = scrape_top_charts(limit=args.limit, country=args.country)

    if not results:
        print("❌ No results returned.")
        sys.exit(1)

    print(f"\n✅ Top {len(results)} songs:\n")
    for i, s in enumerate(results, 1):
        print(f"  {i:>2}. {s['title']} — {s['artist']}")
        print(f"       {s['url']}")
    sys.exit(0)
