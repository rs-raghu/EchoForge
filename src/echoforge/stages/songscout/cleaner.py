from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from pathlib import Path
from typing import Any, Iterable

from echoforge.core.paths import SONGSCOUT_DATA_DIR

RAW_DATA_PATH = SONGSCOUT_DATA_DIR / "youtube_charts_raw.json"
CLEAN_DATA_PATH = SONGSCOUT_DATA_DIR / "youtube_charts_clean.json"

_RE_SPACES = re.compile(r"\s+")
_RE_NON_ALPHANUM = re.compile(r"[^a-z0-9]+")
_RE_INT = re.compile(r"\d+")
_RE_RANK = re.compile(r"^#?\d{1,3}$")
_RE_VIEWS = re.compile(r"^\d+(?:\.\d+)?\s*[kmb]?\s*(?:views)?$", re.I)
_RE_DATE = re.compile(
    r"\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?\s+\d{1,2},?\s+\d{4}\b|\b\d{4}-\d{2}-\d{2}\b",
    re.I,
)
_RE_ARTIST_SPLIT = re.compile(r"\s*(?:,|&| feat\.? | ft\.? | featuring | x )\s*", re.I)

LABEL_ONLY_VALUES = {
    "last week",
    "previous week",
    "weeks on chart",
    "week on chart",
    "weekly views",
    "views",
    "release date",
    "released",
    "song",
    "artist",
    "rank",
    "title",
    "new",
    "re-entry",
    "reentry",
}
NOISE_LINES = {"●", "•", "·", "-", "—", "–", "#", "▲", "▼", "▬"}


def normalize_space(value: Any) -> str:
    return _RE_SPACES.sub(" ", str(value or "").replace("\u00a0", " ")).strip()


def normalize_key(value: Any) -> str:
    return _RE_NON_ALPHANUM.sub("-", normalize_space(value).lower()).strip("-")


def parse_int(value: Any) -> int | None:
    text = normalize_space(value).replace(",", "")
    if not text or text.lower() in {"-", "—", "new"}:
        return None
    match = _RE_INT.search(text)
    return int(match.group(0)) if match else None


def is_rank_line(value: str) -> bool:
    return bool(_RE_RANK.match(normalize_space(value)))


def looks_like_views(value: str) -> bool:
    return bool(_RE_VIEWS.match(normalize_space(value).replace(",", "")))


def looks_like_date(value: str) -> bool:
    return bool(_RE_DATE.search(normalize_space(value)))


def is_noise_line(line: str) -> bool:
    cleaned = normalize_space(line)
    return not cleaned or cleaned in NOISE_LINES


def is_metric_or_label_line(line: str) -> bool:
    low = normalize_space(line).lower().strip(" :-–—")
    return low in LABEL_ONLY_VALUES or is_rank_line(low) or looks_like_views(low) or looks_like_date(low)


def compact_lines(raw_lines: Iterable[Any]) -> list[str]:
    lines: list[str] = []
    seen: set[str] = set()
    for raw in raw_lines:
        line = normalize_space(raw)
        if not line:
            continue
        key = line.lower()
        if key in seen:
            continue
        seen.add(key)
        lines.append(line)
    return lines


def title_artist_from_lines(lines: list[str]) -> tuple[str, str]:
    start = 1 if lines and is_rank_line(lines[0]) else 0
    useful: list[str] = []
    for line in lines[start:]:
        if is_noise_line(line) or is_metric_or_label_line(line):
            continue
        useful.append(line)

    if not useful:
        return "", ""
    if len(useful) == 1:
        return useful[0], ""
    return useful[0], useful[1]


def choose_title_artist(raw: dict[str, Any], lines: list[str]) -> tuple[str, str]:
    title_hint = normalize_space(raw.get("title_hint"))
    artist_hint = normalize_space(raw.get("artist_hint"))
    line_title, line_artist = title_artist_from_lines(lines)

    title = title_hint if title_hint and title_hint.lower() not in {"song", "title", "top songs"} else line_title
    artist = artist_hint if artist_hint and artist_hint != title else line_artist

    # Sometimes YouTube gives a merged title hint like "Song Artist".
    if line_title and line_artist:
        title_key = normalize_key(title)
        if normalize_key(line_title) in title_key and normalize_key(line_artist) in title_key:
            title = line_title
            artist = line_artist

    return normalize_space(title), normalize_space(artist)


def unique_song_id(title: str, artist: str) -> str:
    # Keep historical ASCII IDs; non-ASCII identities must not collapse to ::.
    def identity(value):
        value = unicodedata.normalize("NFC", normalize_space(value)).casefold()
        return normalize_key(value) if value.isascii() else value
    base = f"{identity(title)}::{identity(artist)}"
    return hashlib.sha256(base.encode("utf-8")).hexdigest()[:16]


def clean_row(raw: dict[str, Any], fallback_rank: int | None = None) -> dict[str, Any] | None:
    lines = compact_lines(raw.get("lines") or [])
    rank = parse_int(raw.get("rank_attr"))
    if rank is None and lines:
        rank = parse_int(lines[0])
    if rank is None:
        rank = fallback_rank

    title, artist = choose_title_artist(raw, lines)
    if not title or not artist:
        return None

    youtube_url = normalize_space(raw.get("video_url"))
    thumbnail_url = normalize_space(raw.get("thumbnail_url"))

    return {
        "id": unique_song_id(title, artist),
        "rank": rank,
        "title": title,
        "artist": artist,
        "youtube_url": youtube_url or None,
        "thumbnail_url": thumbnail_url or None,
    }


def clean_rows(raw_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    cleaned: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    for index, raw in enumerate(raw_rows, start=1):
        song = clean_row(raw, fallback_rank=index)
        if not song:
            continue
        if song["id"] in seen_ids:
            continue
        seen_ids.add(song["id"])
        cleaned.append(song)

    cleaned.sort(key=lambda s: (s.get("rank") or 999999, s.get("title", "").lower()))
    return cleaned


def clean_raw_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    return clean_rows(payload.get("rows") or [])


def clean_raw_file(raw_path: Path = RAW_DATA_PATH, clean_path: Path = CLEAN_DATA_PATH) -> list[dict[str, Any]]:
    if not raw_path.exists():
        raise FileNotFoundError(f"Raw SongScout file not found: {raw_path}")

    payload = json.loads(raw_path.read_text(encoding="utf-8"))
    songs = clean_raw_payload(payload)

    clean_path.parent.mkdir(parents=True, exist_ok=True)
    clean_path.write_text(json.dumps({"count": len(songs), "songs": songs}, indent=2, ensure_ascii=False), encoding="utf-8")
    return songs
