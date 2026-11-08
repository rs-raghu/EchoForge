from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from playwright.sync_api import sync_playwright

from paths import SONGSCOUT_DB_PATH, SONGSCOUT_RAW_JSON, ensure_runtime_dirs

YOUTUBE_CHARTS_URL = "https://charts.youtube.com/charts/TopSongs/global/weekly"

EXTRACT_CHART_ROWS_JS = r"""
() => {
  const textCache = new WeakMap();
  const childrenCache = new WeakMap();

  function getChildren(el) {
    if (!childrenCache.has(el)) {
      const out = [];
      const walk = (node) => {
        if (node && node.nodeType === Node.ELEMENT_NODE) {
          out.push(node);
          if (node.shadowRoot) walk(node.shadowRoot);
        }
        for (const child of (node.children || [])) walk(child);
      };
      walk(el);
      childrenCache.set(el, out);
    }
    return childrenCache.get(el);
  }

  function getText(el) {
    if (!textCache.has(el)) {
      const raw = el.innerText || el.textContent || "";
      textCache.set(el, raw.replace(/\u00a0/g, " ").replace(/[ \t]+/g, " ").trim());
    }
    return textCache.get(el);
  }

  function firstLink(nodes) {
    for (const n of nodes) {
      const ep = n.getAttribute ? n.getAttribute("endpoint") || "" : "";
      if (ep) {
        try {
          const parsed = JSON.parse(ep);
          const rawUrl = parsed?.urlEndpoint?.url || parsed?.watchEndpoint?.videoId;
          if (rawUrl) {
            if (rawUrl.startsWith("http")) return rawUrl;
            return `https://www.youtube.com/watch?v=${rawUrl}`;
          }
        } catch {}
      }
      if ((n.tagName || "").toLowerCase() === "a") {
        const href = n.getAttribute("href") || "";
        if (href && (href.includes("watch") || href.includes("youtu.be"))) {
          try { return new URL(href, location.href).href; } catch { return href; }
        }
      }
    }
    return "";
  }

  function firstImage(nodes) {
    for (const img of nodes) {
      if ((img.tagName || "").toLowerCase() !== "img") continue;
      const src = img.currentSrc || img.getAttribute("src") || img.getAttribute("data-src") || "";
      if (src && !src.startsWith("data:")) return src;
    }
    return "";
  }

  const all = getChildren(document);
  const rows = [];
  const seen = new Set();

  for (const el of all) {
    const lines = getText(el).split(/\n+/).map(x => x.trim()).filter(Boolean);
    if (lines.length < 3 || lines.length > 20) continue;
    if (!/^#?\d{1,3}$/.test(lines[0])) continue;

    const key = lines.slice(0, 3).join("|");
    if (seen.has(key)) continue;
    seen.add(key);

    const children = getChildren(el);
    rows.push({
      lines: lines,
      thumbnail_url: firstImage(children),
      video_url: firstLink(children),
    });
  }
  return rows;
}
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def slugify(text: str) -> str:
    slug = re.sub(r"[^\w\s-]", "", text.lower()).strip()
    return re.sub(r"[-\s]+", "_", slug)


def make_song_id(title: str, artist: str) -> str:
    return f"{slugify(title)}__{slugify(artist)}"


def get_db() -> sqlite3.Connection:
    ensure_runtime_dirs()
    conn = sqlite3.connect(SONGSCOUT_DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_database() -> None:
    with get_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS songs (
                id TEXT PRIMARY KEY,
                rank INTEGER,
                title TEXT NOT NULL,
                artist TEXT NOT NULL,
                youtube_url TEXT,
                thumbnail_url TEXT,
                status TEXT NOT NULL DEFAULT 'new',
                project_dir TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS metadata (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_songs_status ON songs(status);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_songs_rank ON songs(rank);")


def add_or_update_song(
    title: str,
    artist: str,
    *,
    rank: int | None = None,
    youtube_url: str | None = None,
    thumbnail_url: str | None = None,
) -> str:
    init_database()
    song_id = make_song_id(title, artist)
    now = now_iso()

    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO songs (id, rank, title, artist, youtube_url, thumbnail_url, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, 'new', ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                rank = excluded.rank,
                youtube_url = COALESCE(excluded.youtube_url, songs.youtube_url),
                thumbnail_url = COALESCE(excluded.thumbnail_url, songs.thumbnail_url),
                updated_at = excluded.updated_at
            """,
            (song_id, rank, title, artist, youtube_url, thumbnail_url, now, now),
        )
    return song_id


def get_next_song() -> dict[str, Any] | None:
    init_database()
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM songs WHERE status = 'new' ORDER BY rank ASC, created_at ASC LIMIT 1"
        ).fetchone()
        return dict(row) if row else None


def mark_song_status(song_id: str, status: str, *, project_dir: str | None = None) -> None:
    init_database()
    now = now_iso()
    with get_db() as conn:
        if project_dir:
            conn.execute(
                "UPDATE songs SET status = ?, project_dir = ?, updated_at = ? WHERE id = ?",
                (status, project_dir, now, song_id),
            )
        else:
            conn.execute(
                "UPDATE songs SET status = ?, updated_at = ? WHERE id = ?",
                (status, now, song_id),
            )


def get_workflow_counts() -> dict[str, int]:
    init_database()
    with get_db() as conn:
        rows = conn.execute("SELECT status, COUNT(*) as cnt FROM songs GROUP BY status").fetchall()
        return {row["status"]: row["cnt"] for row in rows}


def reset_song(identifier: str | None = None) -> list[dict[str, Any]]:
    """Reset one or more songs to 'new' status so they can be processed again."""
    init_database()
    now = now_iso()
    with get_db() as conn:
        if not identifier or identifier in ("current", "latest"):
            row = conn.execute(
                "SELECT id, title, artist, status FROM songs WHERE status != 'new' ORDER BY updated_at DESC LIMIT 1"
            ).fetchone()
            if not row:
                return []
            conn.execute("UPDATE songs SET status = 'new', updated_at = ? WHERE id = ?", (now, row["id"]))
            return [dict(row)]
        elif identifier in ("all", "*"):
            rows = conn.execute(
                "SELECT id, title, artist, status FROM songs WHERE status != 'new'"
            ).fetchall()
            if not rows:
                return []
            conn.execute("UPDATE songs SET status = 'new', updated_at = ? WHERE status != 'new'", (now,))
            return [dict(r) for r in rows]
        else:
            rows = conn.execute(
                "SELECT id, title, artist, status FROM songs WHERE id = ? OR title LIKE ? OR artist LIKE ?",
                (identifier, f"%{identifier}%", f"%{identifier}%"),
            ).fetchall()
            if not rows:
                return []
            conn.execute(
                "UPDATE songs SET status = 'new', updated_at = ? WHERE id = ? OR title LIKE ? OR artist LIKE ?",
                (now, identifier, f"%{identifier}%", f"%{identifier}%"),
            )
            return [dict(r) for r in rows]


def parse_chart_row(raw: dict[str, Any]) -> dict[str, Any] | None:
    lines = [re.sub(r"\s+", " ", x).strip() for x in raw.get("lines", []) if x.strip()]
    if len(lines) < 4:
        return None

    # Line 0: Chart Rank (#1, 2, 3...)
    rank_match = re.search(r"\d+", lines[0])
    rank = int(rank_match.group(0)) if rank_match else None

    # Line 1: Movement / trend badge ("New", "1", "●", "-", "▲2")
    # Line 2: Real Song Title
    # Line 3: Real Artist Name
    title = lines[2]
    artist = lines[3]

    return {
        "rank": rank,
        "title": title,
        "artist": artist,
        "youtube_url": raw.get("video_url") or None,
        "thumbnail_url": raw.get("thumbnail_url") or None,
    }


def scrape_and_sync_chart(max_songs: int = 100, *, headless: bool = True) -> int:
    """Scrape the full YouTube Top Songs chart (100 songs) and save into SQLite."""
    init_database()
    print(f"[*] Connecting to YouTube Charts ({YOUTUBE_CHARTS_URL})...")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        page = browser.new_page(viewport={"width": 1440, "height": 1100})
        page.goto(YOUTUBE_CHARTS_URL, wait_until="domcontentloaded", timeout=45_000)

        # Dismiss cookies / consent banner if present
        try:
            page.get_by_role("button", name=re.compile("Accept|Agree|No thanks", re.I)).first.click(timeout=3000)
        except Exception:
            pass

        page.wait_for_timeout(2000)

        collected: dict[str, dict] = {}

        # Scroll in increments to trigger lazy-loading of all 100 songs
        print("[*] Scrolling to load all 100 chart entries...")
        for _ in range(25):
            current_batch = page.evaluate(EXTRACT_CHART_ROWS_JS)
            for row in current_batch:
                cleaned = parse_chart_row(row)
                if cleaned and cleaned["title"] and cleaned["artist"]:
                    key = make_song_id(cleaned["title"], cleaned["artist"])
                    if key not in collected:
                        collected[key] = cleaned

            if len(collected) >= max_songs:
                break

            page.mouse.wheel(0, 2200)
            page.wait_for_timeout(700)

        browser.close()

    if not collected:
        print("[!] No chart rows found on page.")
        return 0

    # Sort songs by rank
    sorted_songs = sorted(
        collected.values(),
        key=lambda item: (item.get("rank") is None, item.get("rank") or 9999),
    )

    saved_count = 0
    for item in sorted_songs[:max_songs]:
        add_or_update_song(
            title=item["title"],
            artist=item["artist"],
            rank=item.get("rank"),
            youtube_url=item.get("youtube_url"),
            thumbnail_url=item.get("thumbnail_url"),
        )
        saved_count += 1

    # Record today's date upon successful scrape
    today_iso = datetime.now(timezone.utc).date().isoformat()
    set_metadata("last_scraped_date", today_iso)

    return saved_count


def get_metadata(key: str) -> str | None:
    """Read a key from the metadata table."""
    init_database()
    with get_db() as conn:
        row = conn.execute("SELECT value FROM metadata WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else None


def set_metadata(key: str, value: str) -> None:
    """Store or update a key-value pair in metadata."""
    init_database()
    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO metadata (key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (key, value),
        )


def has_any_songs() -> bool:
    """Check if the database contains at least one song."""
    init_database()
    with get_db() as conn:
        row = conn.execute("SELECT 1 FROM songs LIMIT 1").fetchone()
        return row is not None
