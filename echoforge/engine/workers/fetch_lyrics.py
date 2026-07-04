"""
engine/workers/fetch_lyrics.py

Fetches synced (.lrc) or plain-text (.txt) lyrics and saves them
to the song's workspace directory.

Bug 2 fix — sys.exit(0/1) instead of return True/False.

CLI USAGE:
    python fetch_lyrics.py --title "Blinding Lights" --artist "The Weeknd" \\
                           --workspace ./workspaces/abc123
"""

import argparse
import os
import re
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[3]
sys.path.append(str(ROOT_DIR))

from echoforge.utils.logger import get_logger

log = get_logger(__name__)

try:
    import syncedlyrics
except ImportError:
    log.error("❌ 'syncedlyrics' not installed. Run: pip install syncedlyrics")
    syncedlyrics = None


def fetch(song: dict) -> bool:
    """
    Fetch lyrics for *song*.
    Saves lyrics.lrc (synced) or lyrics.txt (plain) in workspace_dir.
    Returns True on success, False if nothing was found.
    """
    if not syncedlyrics:
        log.error("❌ syncedlyrics missing — cannot fetch lyrics.")
        return False

    title         = song.get("title", "").strip()
    artist        = song.get("artist", "").strip()
    workspace_dir = song.get("workspace_dir")

    if not title or not workspace_dir:
        log.error("❌ Missing title or workspace_dir.")
        return False

    lrc_path = os.path.join(workspace_dir, "lyrics.lrc")
    txt_path = os.path.join(workspace_dir, "lyrics.txt")

    # Already fetched (manual upload or prior run)
    if os.path.exists(lrc_path) or os.path.exists(txt_path):
        log.info("✅ Lyrics already in workspace — skipping fetch.")
        return True

    query = f"{title} {artist}".strip()
    log.info("📝 Searching for lyrics: '%s'", query)

    try:
        content = syncedlyrics.search(query)

        if not content:
            log.warning("⚠️  No lyrics found for '%s'.", query)
            return False

        is_synced = bool(re.search(r"\[\d{2}:\d{2}\.\d{2,3}\]", content))

        if is_synced:
            with open(lrc_path, "w", encoding="utf-8") as fh:
                fh.write(content)
            log.info("✅ Synced lyrics saved: %s", lrc_path)
        else:
            clean = "\n".join(
                line.strip() for line in content.split("\n") if line.strip()
            )
            with open(txt_path, "w", encoding="utf-8") as fh:
                fh.write(clean)
            log.info("✅ Plain-text lyrics saved: %s", txt_path)

        return True

    except Exception as exc:
        log.exception("❌ Unexpected error fetching lyrics: %s", exc)
        return False


# ── CLI ────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="EchoForge Lyrics Fetcher")
    parser.add_argument("--title",     required=True)
    parser.add_argument("--artist",    required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()

    os.makedirs(args.workspace, exist_ok=True)
    song = {"title": args.title, "artist": args.artist, "workspace_dir": args.workspace}
    ok   = fetch(song)
    print(f"\n{'✅ Success' if ok else '❌ Failed'}")
    sys.exit(0 if ok else 1)
