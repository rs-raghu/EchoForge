"""
discovery/chart_scraper.py

Scrapes the YouTube Charts using Playwright and BeautifulSoup to bypass
the API blocking and A/B testing issues of ytmusicapi.

Changes from original
─────────────────────
• Swapped `ytmusicapi` for a direct DOM scrape of charts.youtube.com.
• Uses Playwright to render the JS, then parses the table with BeautifulSoup.
• Input, output (`list[dict]`), and CLI remain exactly the same.

CLI USAGE:
    python discovery/chart_scraper.py --limit 10
"""

import argparse
import sys
import os
import json
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT_DIR))

from echoforge.utils.logger import get_logger

log = get_logger(__name__)

try:
    from playwright.sync_api import sync_playwright
    from bs4 import BeautifulSoup
except ImportError:
    log.error("❌ Dependencies missing. Run: pip install playwright beautifulsoup4 && playwright install")
    sync_playwright = None
    BeautifulSoup = None


def scrape_top_charts(limit: int = 20, country: str = "US") -> list[dict]:
    """
    Fetch the top *limit* trending songs directly from charts.youtube.com.

    Returns a list of dicts:
        {
            "video_id": str,
            "title":    str,
            "artist":   str,
            "url":      str,   ← full YouTube watch URL
        }

    Returns an empty list on any failure (caller handles gracefully).
    """
    if not sync_playwright:
        raise ImportError("Playwright or BeautifulSoup not installed.")

    # Map country codes to the YouTube Charts URL path structure
    country_path = "global" if country.upper() == "GLOBAL" else country.lower()
    url = f"https://charts.youtube.com/charts/TopSongs/{country_path}/weekly"

    log.info("🔍 Scraping YouTube Charts via Playwright (%s)...", url)

    try:
        # 1. Spin up headless browser to execute JavaScript
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(url)

            # Wait up to 15 seconds for the JS table to actually render on the screen
            page.wait_for_selector('div.data-table-container', timeout=15000)
            html_content = page.content()
            browser.close()

        # 2. Parse the rendered HTML
        soup = BeautifulSoup(html_content, 'html.parser')
        rows = soup.find_all('div', class_='data-table-container style-scope ytmc-entry-row')

        if not rows:
            log.warning("⚠️  Playwright loaded the page but found no chart rows.")
            return []

        songs = []
        for row in rows:
            if len(songs) >= limit:
                break

            # Extract Title
            title_elem = row.find('div', id='entity-title')
            if not title_elem:
                continue
            title = title_elem.text.strip()

            # Extract URL and Video ID from the JSON 'endpoint' attribute
            endpoint_str = title_elem.get('endpoint')
            if not endpoint_str:
                continue
                
            try:
                ep_data = json.loads(endpoint_str)
                watch_url = ep_data['urlEndpoint']['url']
                video_id = watch_url.split('v=')[-1].split('&')[0]
            except (json.JSONDecodeError, KeyError, IndexError):
                continue

            # Extract Artists
            artist_spans = row.find_all('span', class_='artistName')
            artists = [a.text.strip() for a in artist_spans]
            artist_str = ", ".join(artists) if artists else "Unknown Artist"

            songs.append({
                "video_id": video_id,
                "title":    title,
                "artist":   artist_str,
                "url":      watch_url,
            })

        log.info("✅ Scraped %d songs from charts.youtube.com.", len(songs))
        return songs

    except Exception as exc:
        log.error("❌ Playwright scrape failed: %s", exc)
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
