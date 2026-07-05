from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import requests


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def parse_lrc(lrc_text: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    pattern = re.compile(r"\[(\d{1,2}):(\d{2})(?:\.(\d{1,3}))?\](.*)")
    for raw in lrc_text.splitlines():
        match = pattern.match(raw.strip())
        if not match:
            continue
        minutes = int(match.group(1))
        seconds = int(match.group(2))
        millis = int((match.group(3) or "0").ljust(3, "0")[:3])
        text = match.group(4).strip()
        if text:
            out.append({"time": round(minutes * 60 + seconds + millis / 1000, 3), "text": text})
    return out


def plain_from_lrc(lrc_text: str) -> str:
    return "\n".join(item["text"] for item in parse_lrc(lrc_text)).strip()


def score(candidate: dict[str, Any], title: str, artist: str) -> int:
    points = 100 if str(candidate.get("syncedLyrics") or "").strip() else 0
    points += 10 if str(candidate.get("plainLyrics") or "").strip() else 0
    track = str(candidate.get("trackName") or "").lower()
    artist_name = str(candidate.get("artistName") or "").lower()
    if title.lower() in track:
        points += 20
    first_artist_word = artist.lower().split()[0] if artist.split() else ""
    if first_artist_word and first_artist_word in artist_name:
        points += 10
    if "instrumental" in track or "karaoke" in track:
        points -= 50
    return points


def search_lrclib(title: str, artist: str) -> list[dict[str, Any]]:
    base = os.getenv("LRCLIB_BASE_URL", "https://lrclib.net").rstrip("/")
    url = f"{base}/api/search?{urlencode({'track_name': title, 'artist_name': artist})}"
    response = requests.get(url, timeout=20, headers={"User-Agent": "EchoForge/0.1"})
    response.raise_for_status()
    payload = response.json()
    return payload if isinstance(payload, list) else []


def fetch_synced_lyrics(project_dir: Path, review: dict[str, Any]) -> dict[str, Any]:
    lyrics_dir = project_dir / "lyrics"
    sync_dir = project_dir / "sync"
    lyrics_dir.mkdir(parents=True, exist_ok=True)
    sync_dir.mkdir(parents=True, exist_ok=True)

    title = str(review.get("search_title") or review.get("display_title") or "").strip()
    artist = str(review.get("search_artist") or review.get("display_artist") or "").strip()
    status_path = lyrics_dir / "lyrics_status.json"

    if not title or not artist:
        result = {"ok": False, "source": "lrclib", "found": False, "reason": "missing title or artist"}
        write_json(status_path, result)
        return result

    try:
        candidates = search_lrclib(title, artist)
    except Exception as exc:
        result = {"ok": False, "source": "lrclib", "found": False, "reason": str(exc)}
        write_json(status_path, result)
        return result

    synced = [item for item in candidates if str(item.get("syncedLyrics") or "").strip()]
    if not synced:
        result = {"ok": True, "source": "lrclib", "found": False, "candidate_count": len(candidates), "reason": "no synced lyrics found", "checked_at": now_iso()}
        write_json(status_path, result)
        return result

    best = max(synced, key=lambda item: score(item, title, artist))
    lrc_text = str(best.get("syncedLyrics") or "").strip()
    plain_text = str(best.get("plainLyrics") or "").strip() or plain_from_lrc(lrc_text)
    lines = parse_lrc(lrc_text)

    lrc_path = lyrics_dir / "synced_lyrics.lrc"
    json_path = lyrics_dir / "synced_lyrics.json"
    lyrics_path = lyrics_dir / "lyrics.txt"
    original_path = lyrics_dir / "lyrics_original.txt"
    candidate_path = sync_dir / "candidate_online_lrc_best.json"

    lrc_path.write_text(lrc_text + "\n", encoding="utf-8")
    lyrics_path.write_text(plain_text + "\n", encoding="utf-8")
    original_path.write_text(plain_text + "\n", encoding="utf-8")
    write_json(json_path, {"source": "lrclib", "candidate": best, "lines": lines})
    write_json(candidate_path, {"source": "lrclib", "candidate": best, "lines": lines})

    result = {
        "ok": True,
        "source": "lrclib",
        "found": True,
        "candidate_count": len(candidates),
        "synced_candidate_count": len(synced),
        "line_count": len(lines),
        "lrc_path": str(lrc_path),
        "json_path": str(json_path),
        "lyrics_path": str(lyrics_path),
        "checked_at": now_iso(),
    }
    write_json(status_path, result)
    return result
