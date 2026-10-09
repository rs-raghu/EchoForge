from __future__ import annotations

from echoforge.core.storage import atomic_text

import html
import os
import re
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

import requests


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def write_json(path, payload):
    from echoforge.core.storage import atomic_json
    atomic_json(path, payload)


def load_env(project_dir: Path) -> None:
    for parent in [project_dir.resolve(), *project_dir.resolve().parents]:
        env_path = parent / ".env"
        if env_path.exists():
            for line in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))
            return


class TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self.skip = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript"}:
            self.skip = True
        if tag in {"br", "p", "div"}:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript"}:
            self.skip = False
        if tag in {"p", "div"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self.skip:
            self.parts.append(data)

    def get_text(self) -> str:
        return re.sub(r"\n{3,}", "\n\n", html.unescape("".join(self.parts))).strip()


def strip_html(fragment: str) -> str:
    parser = TextExtractor()
    parser.feed(fragment)
    return parser.get_text()


def clean_lyrics(text: str) -> str:
    lines = []
    for line in text.splitlines():
        line = line.strip()
        low = line.lower()
        if not line:
            if lines and lines[-1] != "":
                lines.append("")
            continue
        if low.startswith(("contributors", "translations", "you might also like", "embed", "read more")):
            continue
        if re.fullmatch(r"\d+", low):
            continue
        lines.append(line)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def genius_search(title: str, artist: str, token: str) -> dict[str, Any] | None:
    response = requests.get(
        "https://api.genius.com/search",
        params={"q": f"{title} {artist}".strip()},
        headers={"Authorization": f"Bearer {token}", "User-Agent": "EchoForge/0.1"},
        timeout=20,
    )
    response.raise_for_status()
    hits = response.json().get("response", {}).get("hits", [])
    return hits[0].get("result") if hits else None


def scrape_lyrics(url: str) -> str:
    response = requests.get(url, timeout=25, headers={"User-Agent": "Mozilla/5.0 EchoForge/0.1"})
    response.raise_for_status()
    blocks = re.findall(r'<div[^>]+data-lyrics-container="true"[^>]*>(.*?)</div>', response.text, flags=re.I | re.S)
    if blocks:
        return clean_lyrics("\n".join(strip_html(block) for block in blocks))
    return ""


def fetch_genius_lyrics(project_dir: Path, review: dict[str, Any]) -> dict[str, Any]:
    load_env(project_dir)
    lyrics_dir = project_dir / "lyrics"
    lyrics_dir.mkdir(parents=True, exist_ok=True)
    status_path = lyrics_dir / "lyrics_status.json"

    token = os.getenv("GENIUS_ACCESS_TOKEN")
    if not token:
        result = {"ok": False, "source": "genius", "found": False, "reason": "GENIUS_ACCESS_TOKEN not set"}
        write_json(status_path, result)
        return result

    title = str(review.get("search_title") or review.get("display_title") or "").strip()
    artist = str(review.get("search_artist") or review.get("display_artist") or "").strip()

    try:
        hit = genius_search(title, artist, token)
        if not hit or not hit.get("url"):
            result = {"ok": True, "source": "genius", "found": False, "reason": "no search result"}
            write_json(status_path, result)
            return result
        lyrics = scrape_lyrics(hit["url"])
    except Exception as exc:
        result = {"ok": False, "source": "genius", "found": False, "reason": str(exc)}
        write_json(status_path, result)
        return result

    if not lyrics or len(lyrics) < 20:
        result = {"ok": True, "source": "genius", "found": False, "reason": "no usable lyrics"}
        write_json(status_path, result)
        return result

    lyrics_path = lyrics_dir / "lyrics.txt"
    original_path = lyrics_dir / "lyrics_original.txt"
    atomic_text(lyrics_path, lyrics + "\n")
    atomic_text(original_path, lyrics + "\n")
    result = {"ok": True, "source": "genius", "found": True, "lyrics_path": str(lyrics_path), "url": hit.get("url"), "checked_at": now_iso()}
    write_json(status_path, result)
    return result
