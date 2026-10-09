from __future__ import annotations

import argparse
import json
import os
import re
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _read_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _read_text(path: Path, max_chars: Optional[int] = None) -> str:
    if not path.exists():
        return ""
    text = path.read_text(encoding="utf-8", errors="ignore")
    if max_chars and len(text) > max_chars:
        return text[:max_chars].rstrip()
    return text.strip()


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def _clean_spaces(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _slug_hashtag(text: str) -> str:
    text = str(text or "").lower()
    text = re.sub(r"[^a-z0-9]+", "", text)
    return text


def _tagify(text: str) -> str:
    text = _slug_hashtag(text)
    return f"#{text}" if text else ""


def _split_artists(artist_text: str) -> List[str]:
    text = _clean_spaces(artist_text)
    if not text:
        return []
    # Keep names intact, split only on common separators.
    parts = re.split(r"\s*(?:&|,| x | X | feat\.?| ft\.?| featuring | with | and )\s*", text, flags=re.I)
    out: List[str] = []
    for part in parts:
        part = _clean_spaces(part)
        if part and part.lower() not in {"various artists", "unknown"} and part not in out:
            out.append(part)
    return out or [text]


def _dedupe(items: List[str]) -> List[str]:
    seen = set()
    out = []
    for item in items:
        item = _clean_spaces(item)
        if not item:
            continue
        key = item.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def _limit_youtube_tags(tags: List[str], max_total_chars: int = 450) -> List[str]:
    """Keep tags within a safe YouTube API tag budget.

    YouTube tags are a list in snippet.tags, but upload/update calls can fail when the
    total metadata is too large. Keep this conservative and preserve priority order.
    """
    out: List[str] = []
    total = 0
    for tag in _dedupe(tags):
        if len(tag) > 95:
            tag = tag[:95].rstrip()
        # Approximate quote/comma overhead.
        next_total = total + len(tag) + 2
        if next_total > max_total_chars:
            break
        out.append(tag)
        total = next_total
    return out


def _project_context(project: Path) -> Dict[str, Any]:
    project = Path(project)
    state = _read_json(project / "project_state.json")
    review = _read_json(project / "metadata_review.json")
    manifest = _read_json(project / "asset_manifest.json")

    def pick(*keys: str, default: str = "") -> str:
        for source in (review, state, manifest):
            for key in keys:
                value = source.get(key)
                if isinstance(value, dict):
                    for sub in ("value", "text", "path"):
                        if source.get(key, {}).get(sub):
                            return _clean_spaces(source[key][sub])
                elif value:
                    return _clean_spaces(value)
        return default

    song_title = pick("display_title", "song_title", "title")
    artist_text = pick("display_artist", "artist_text", "artists", "artist")
    album = pick("album", "album_name")
    year = pick("year", "release_year")
    genre = pick("genre", "style")
    lyrics_text = _read_text(project / "lyrics" / "lyrics.txt", max_chars=4300)

    # Fallbacks from folder name if needed.
    if not song_title:
        song_title = project.name.split("_", 1)[-1].replace("-", " ").title()
    if not artist_text:
        artist_text = "Unknown Artist"

    artists = _split_artists(artist_text)
    return {
        "song_title": song_title,
        "artist_text": artist_text,
        "artists": artists,
        "album": album,
        "year": year,
        "genre": genre,
        "lyrics_text": lyrics_text,
    }


def _find_gemini_key(root: Path) -> str:
    env_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if env_key:
        return env_key.strip()
    candidates = [
        root / ".secrets" / "gemini_api_key.txt",
        root / ".secrets" / "GEMINI_API_KEY.txt",
        root / ".secrets" / "google_api_key.txt",
        root / ".secrets" / "GOOGLE_API_KEY.txt",
    ]
    for path in candidates:
        if path.exists():
            text = path.read_text(encoding="utf-8", errors="ignore").strip()
            if text:
                return text
    env_file = root / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8", errors="ignore").splitlines():
            if line.strip().startswith(("GEMINI_API_KEY=", "GOOGLE_API_KEY=")):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


def _gemini_models() -> List[str]:
    env_model = os.environ.get("GEMINI_MODEL", "").strip()
    # Try cheaper/lighter models first. Some projects have quota=0 for specific models.
    defaults = [
        "gemini-3.5-flash-lite",
        "gemini-3.5-flash",
        "gemini-2.5-flash-lite",
        "gemini-2.0-flash-lite",
        "gemini-2.5-flash",
        "gemini-2.0-flash",
        "gemini-1.5-flash",
    ]
    if env_model:
        return _dedupe([env_model] + defaults)
    return defaults


def _extract_json_object(text: str) -> Dict[str, Any]:
    text = text.strip()
    # Strip markdown code fences if present.
    text = re.sub(r"^```(?:json)?", "", text, flags=re.I).strip()
    text = re.sub(r"```$", "", text).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        text = text[start : end + 1]
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _call_gemini(root: Path, context: Dict[str, Any], forced_model: Optional[str] = None) -> Tuple[Dict[str, Any], Dict[str, Any], Optional[str]]:
    key = _find_gemini_key(root)
    if not key:
        return {}, {"used": False, "model": None, "raw_fields": {}}, "Gemini API key not found in .secrets or environment."

    models = [forced_model] if forced_model else _gemini_models()
    models = [m for m in models if m]

    # Keep prompt tiny: Gemini enriches album/year/genre/tags only. Description stays deterministic.
    prompt = {
        "task": "Return ONLY valid JSON. Research/infer likely YouTube metadata enrichment for a lyrics video. If unsure, use empty string.",
        "song_title": context["song_title"],
        "artist_text": context["artist_text"],
        "known_artists": context.get("artists", []),
        "required_schema": {
            "album": "string or empty",
            "year": "4 digit year or empty",
            "genre": "short YouTube-friendly genre such as Dance - Electronic, Pop, Afrobeats, Latin, Hip-Hop, etc.",
            "extra_tags": ["10 to 20 short relevant YouTube tags, no hashtags"],
            "description_hashtags": ["3 to 5 lowercase hashtags, include song and artists"],
        },
        "rules": [
            "Do not invent if uncertain; empty album/year is better than wrong data.",
            "Do not include lyrics.",
            "Do not include markdown.",
        ],
    }
    body = {
        "contents": [{"parts": [{"text": json.dumps(prompt, ensure_ascii=False)}]}],
        "generationConfig": {
            "temperature": 0.2,
            "topP": 0.8,
            "maxOutputTokens": 512,
            "responseMimeType": "application/json",
        },
    }

    last_error = None
    tried = []
    for model in models:
        tried.append(model)
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"
        req = urllib.request.Request(
            url,
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
            parts = payload.get("candidates", [{}])[0].get("content", {}).get("parts", [])
            text = "\n".join(str(p.get("text", "")) for p in parts if isinstance(p, dict))
            fields = _extract_json_object(text)
            if fields:
                return fields, {"used": True, "model": model, "tried_models": tried, "raw_fields": fields}, None
            last_error = f"Gemini returned no parseable JSON for model {model}."
        except urllib.error.HTTPError as exc:
            body_text = exc.read().decode("utf-8", errors="ignore")[:1800]
            last_error = f"Gemini HTTP error {exc.code} on {model}: {body_text}"
            # 429/404/400 can be model/key/project-specific. Try next model.
            if exc.code not in {400, 404, 429}:
                break
        except Exception as exc:
            last_error = f"Gemini error on {model}: {exc}"
            break

    return {}, {"used": False, "model": forced_model or models[0] if models else None, "tried_models": tried, "raw_fields": {}}, last_error


def _safe_title_parts(song_title: str, artist_text: str, album: str, year: str, genre: str) -> str:
    parts = [f"{song_title} - {artist_text} (Lyrics)"]
    if year:
        parts.append(year)
    if album:
        parts.append(f"Album : {album}")
    if genre:
        parts.append(genre)
    title = " | ".join(parts)
    # YouTube title max is 100 chars. Keep essential part first.
    if len(title) <= 100:
        return title
    parts = [f"{song_title} - {artist_text} (Lyrics)"]
    if year:
        parts.append(year)
    if genre:
        parts.append(genre)
    title = " | ".join(parts)
    return title[:100].rstrip(" |-")


def _build_tags(song_title: str, artist_text: str, artists: List[str], gemini_fields: Dict[str, Any]) -> List[str]:
    raw: List[str] = [
        "winsomegin",
        song_title,
        f"{song_title} lyrics",
        f"{song_title} lyric video",
        f"{song_title} lyrics video",
        f"{song_title} song",
        f"{song_title} music",
        f"{song_title} official lyrics",
        f"{song_title} full lyrics",
        artist_text,
        f"{song_title} {artist_text}",
        f"{song_title} {artist_text} lyrics",
    ]
    for artist in artists:
        raw += [
            artist,
            f"{artist} lyrics",
            f"{artist} songs",
            f"{artist} music",
            f"{song_title} {artist}",
            f"{song_title} {artist} lyrics",
        ]
    raw += [
        "lyrics",
        "lyric video",
        "lyrics video",
        "song lyrics",
        "music lyrics",
        "new song lyrics",
        "trending song lyrics",
        "english lyrics",
        "music",
        "song",
    ]
    extra = gemini_fields.get("extra_tags") or []
    if isinstance(extra, list):
        raw += [str(x).replace("#", "") for x in extra]
    return _limit_youtube_tags(raw)


def _build_description(song_title: str, artist_text: str, artists: List[str], lyrics_text: str, tags: List[str], gemini_fields: Dict[str, Any]) -> str:
    gem_hashes = gemini_fields.get("description_hashtags") or []
    hashtags: List[str] = []
    if isinstance(gem_hashes, list):
        hashtags.extend([str(x) if str(x).startswith("#") else _tagify(str(x)) for x in gem_hashes])
    hashtags += [_tagify(song_title)] + [_tagify(a) for a in artists]
    hashtags = _dedupe([h for h in hashtags if h])[:5]
    if not hashtags:
        hashtags = ["#lyrics", "#music", "#lyricvideo"]

    desc_tag_hashes = []
    for tag in tags[:16]:
        h = _tagify(tag)
        if h:
            desc_tag_hashes.append(h)
    desc_tag_hashes = _dedupe(["#song", "#music", "#lyricvideo", "#lyrics", "#winsomegin"] + desc_tag_hashes)[:16]

    search_lines = [song_title.lower()]
    for artist in artists:
        search_lines.append(f"{song_title} {artist}".lower())
    search_lines += [
        f"{song_title} lyrics".lower(),
        f"{song_title} lyric video".lower(),
    ]
    for artist in artists:
        search_lines.append(f"{artist} lyrics".lower())
    search_lines = _dedupe(search_lines)

    lyrics_block = lyrics_text.strip()
    search_block = "\n".join(search_lines)
    description = (
        f"{'  '.join(hashtags)}\n"
        f"🎶{song_title}  -  {artist_text} (Lyrics)\n"
        "🔥 Help us reach 1000 subscribers!\n"
        "🔔 Subscribe and turn on notifications to stay updated with new uploads.\n"
        "👍🏽 Please leave a like, share, and appreciate all the support!\n"
        "________________________________________________________________________\n\n"
        f"📋 Tags: {' '.join(desc_tag_hashes)}\n\n"
        f"{search_block}\n\n"
        "🎤 Lyrics:\n"
        f"{lyrics_block}"
    )
    # YouTube description max is 5000 bytes. Trim safely if needed.
    encoded = description.encode("utf-8")
    if len(encoded) <= 4900:
        return description
    base = description.split("🎤 Lyrics:\n", 1)[0] + "🎤 Lyrics:\n"
    remaining = 4900 - len(base.encode("utf-8")) - 20
    trimmed = lyrics_block.encode("utf-8")[:max(0, remaining)].decode("utf-8", errors="ignore").rstrip()
    return base + trimmed + "\n..."


def build_metadata(project: Path, *, use_gemini: Optional[bool] = None, gemini_model: Optional[str] = None) -> Dict[str, Any]:
    root = _repo_root()
    context = _project_context(project)
    gemini_fields: Dict[str, Any] = {}
    gemini_info: Dict[str, Any] = {"used": False, "model": None, "raw_fields": {}}
    gemini_error: Optional[str] = None

    if use_gemini is None:
        use_gemini = bool(_find_gemini_key(root))

    if use_gemini:
        gemini_fields, gemini_info, gemini_error = _call_gemini(root, context, forced_model=gemini_model)

    album = _clean_spaces(gemini_fields.get("album") or context["album"])
    year = _clean_spaces(gemini_fields.get("year") or context["year"])
    genre = _clean_spaces(gemini_fields.get("genre") or context["genre"])

    song_title = context["song_title"]
    artist_text = context["artist_text"]
    artists = context["artists"]
    tags = _build_tags(song_title, artist_text, artists, gemini_fields)
    title = _safe_title_parts(song_title, artist_text, album, year, genre)
    description = _build_description(song_title, artist_text, artists, context["lyrics_text"], tags, gemini_fields)

    source = "gemini+template" if gemini_info.get("used") else "template"
    metadata = {
        "title": title,
        "description": description,
        "tags": tags,
        "category_id": "10",
        "made_for_kids": False,
        "source": source,
    }

    result = {
        "ok": True,
        "mode": "youtube_metadata_generation",
        "source": source,
        "project_dir": str(Path(project)),
        "song_title": song_title,
        "artist_text": artist_text,
        "artists": artists,
        "album": album,
        "year": year,
        "genre": genre,
        "metadata": metadata,
        "gemini": gemini_info,
        "gemini_error": gemini_error,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "note": "Generated metadata should be reviewed before upload. Only include lyrics in descriptions when you have rights/permission to publish them.",
    }
    output_path = Path(project) / "upload" / "youtube_metadata.json"
    _write_json(output_path, result)
    result["output_path"] = str(output_path)
    return result


def generate_youtube_metadata(project: str | Path, use_gemini: Optional[bool] = None, gemini_model: Optional[str] = None) -> Dict[str, Any]:
    return build_metadata(Path(project), use_gemini=use_gemini, gemini_model=gemini_model)


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate YouTube title, description, tags for an EchoForge project.")
    parser.add_argument("--project", required=True)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--use-gemini", action="store_true")
    group.add_argument("--no-gemini", action="store_true")
    parser.add_argument("--model", default=None, help="Optional Gemini model override, e.g. gemini-2.5-flash-lite")
    args = parser.parse_args()

    use_gemini: Optional[bool]
    if args.use_gemini:
        use_gemini = True
    elif args.no_gemini:
        use_gemini = False
    else:
        use_gemini = None

    result = build_metadata(Path(args.project), use_gemini=use_gemini, gemini_model=args.model)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
