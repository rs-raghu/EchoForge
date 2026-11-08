from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from paths import (
    GEMINI_API_KEY_PATH,
    YOUTUBE_CLIENT_SECRET_PATH,
    YOUTUBE_TOKEN_PATH,
)
from songscout import mark_song_status

YOUTUBE_SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]

GEMINI_MODELS = [
    "gemini-2.5-flash-lite",
    "gemini-flash-latest",
    "gemini-3.5-flash-lite",
    "gemini-2.5-flash",
    "gemini-2.0-flash",
]


def _clean_spaces(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _slug_hashtag(text: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "", str(text or ""))
    return cleaned


def _tagify(text: str) -> str:
    slug = _slug_hashtag(text)
    return f"#{slug}" if slug else ""


def _split_artists(artist_text: str) -> list[str]:
    text = _clean_spaces(artist_text)
    if not text:
        return []
    parts = re.split(
        r"\s*(?:&|,| x | X | feat\.?| ft\.?| featuring | with | and )\s*",
        text,
        flags=re.IGNORECASE,
    )
    out: list[str] = []
    for part in parts:
        clean = _clean_spaces(part)
        if clean and clean.lower() not in {"various artists", "unknown"} and clean not in out:
            out.append(clean)
    return out or [text]


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        clean = _clean_spaces(item)
        if not clean:
            continue
        key = clean.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(clean)
    return out


def _limit_youtube_tags(tags: list[str], max_chars: int = 450) -> list[str]:
    out: list[str] = []
    total = 0
    for tag in _dedupe(tags):
        trimmed = tag[:90].strip() if len(tag) > 90 else tag.strip()
        cost = len(trimmed) + 2
        if total + cost > max_chars:
            break
        out.append(trimmed)
        total += cost
    return out


def _read_project_lyrics(project_dir: Path) -> str:
    txt_path = project_dir / "lyrics.txt"
    if txt_path.is_file():
        return txt_path.read_text(encoding="utf-8", errors="ignore").strip()

    lrc_path = project_dir / "lyrics.lrc"
    if lrc_path.is_file():
        lines = []
        for line in lrc_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            cleaned = re.sub(r"^\[\d+:\d+(?:\.\d+)?\]", "", line).strip()
            if cleaned:
                lines.append(cleaned)
        return "\n".join(lines)

    return ""


def get_gemini_api_key() -> str:
    if os.environ.get("GEMINI_API_KEY"):
        return os.environ["GEMINI_API_KEY"].strip()
    if os.environ.get("GOOGLE_API_KEY"):
        return os.environ["GOOGLE_API_KEY"].strip()
    if GEMINI_API_KEY_PATH.is_file():
        key = GEMINI_API_KEY_PATH.read_text(encoding="utf-8").strip()
        if key:
            return key
    raise RuntimeError(
        f"Gemini API key not found! Place your Gemini API key in '{GEMINI_API_KEY_PATH}' "
        "or set GEMINI_API_KEY in your environment. Gemini AI metadata enrichment is mandatory."
    )


def enrich_with_gemini(song_title: str, artist_text: str, lyrics_sample: str = "") -> dict[str, Any]:
    """Call Gemini to enrich video metadata (album, release year, genre, SEO tags, fun fact).

    Mandatory for all EchoForge releases.
    """
    key = get_gemini_api_key()
    prompt = {
        "task": (
            "You are an expert music SEO and YouTube growth strategist. Research/infer the most accurate, "
            "high-converting YouTube metadata enrichment for this song's official lyrics video. "
            "Return ONLY a valid JSON object matching the required schema."
        ),
        "song_title": song_title,
        "artist": artist_text,
        "lyrics_excerpt": lyrics_sample[:500] if lyrics_sample else "",
        "required_schema": {
            "album": "Album name or EP name (or empty string if non-album single)",
            "year": "4-digit release year (e.g. 2024, 2025, 2026)",
            "genre": "Short standard YouTube music genre (e.g., Pop, Hip-Hop, K-Pop, Dance/Electronic, Latin, R&B, Rock, Afrobeats)",
            "extra_tags": ["12 to 18 high-intent search tags/phrases without hashtags"],
            "description_hashtags": ["4 to 6 lowercase hashtags including artist, title, and genre"],
            "fun_fact": "A short, engaging 1-sentence background info or fact about this song or artist",
        },
        "rules": [
            "Output strictly valid JSON with no markdown formatting.",
            "Do not invent facts if completely unknown.",
        ],
    }

    body = {
        "contents": [{"parts": [{"text": json.dumps(prompt, ensure_ascii=False)}]}],
        "generationConfig": {
            "temperature": 0.2,
            "topP": 0.8,
            "responseMimeType": "application/json",
        },
    }
    payload = json.dumps(body).encode("utf-8")

    last_error: str | None = None
    for model in GEMINI_MODELS:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"
        req = urllib.request.Request(
            url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                resp_json = json.loads(resp.read().decode("utf-8"))
            candidates = resp_json.get("candidates", [])
            if not candidates:
                continue
            parts = candidates[0].get("content", {}).get("parts", [])
            raw_text = "\n".join(str(p.get("text", "")) for p in parts if isinstance(p, dict))
            raw_text = re.sub(r"^```(?:json)?", "", raw_text, flags=re.IGNORECASE).strip()
            raw_text = re.sub(r"```$", "", raw_text).strip()
            parsed = json.loads(raw_text)
            if isinstance(parsed, dict):
                parsed["_model"] = model
                return parsed
        except urllib.error.HTTPError as exc:
            err_body = exc.read().decode("utf-8", errors="ignore")[:300]
            last_error = f"HTTP {exc.code} on {model}: {err_body}"
            # Continue trying fallback models on 404, 400, or 429
            continue
        except Exception as exc:
            last_error = f"{type(exc).__name__} on {model}: {exc}"
            continue

    raise RuntimeError(f"Gemini metadata enrichment failed on all models. Last error: {last_error}")


def build_seo_title(song_title: str, artist_text: str, album: str, year: str, genre: str) -> str:
    base = f"{song_title} - {artist_text} (Lyrics)"
    additions = []
    if year:
        additions.append(year)
    if album and album.lower() != song_title.lower():
        additions.append(f"Album: {album}")
    if genre:
        additions.append(genre)

    candidate = f"{base} | " + " | ".join(additions) if additions else base
    if len(candidate) <= 100:
        return candidate

    # Truncate additions while preserving base title
    for i in range(len(additions) - 1, -1, -1):
        subset = additions[:i]
        candidate = f"{base} | " + " | ".join(subset) if subset else base
        if len(candidate) <= 100:
            return candidate

    return base[:100].rstrip(" |-")


def build_seo_tags(
    song_title: str,
    artist_text: str,
    artists: list[str],
    extra_tags: list[str],
) -> list[str]:
    raw: list[str] = [
        "winsomegin",
        song_title,
        f"{song_title} lyrics",
        f"{song_title} lyric video",
        f"{song_title} lyrics video",
        f"{song_title} song",
        f"{song_title} official lyrics",
        artist_text,
        f"{song_title} {artist_text}",
        f"{song_title} {artist_text} lyrics",
    ]
    for artist in artists:
        raw.extend([
            artist,
            f"{artist} lyrics",
            f"{artist} songs",
            f"{song_title} {artist}",
        ])
    raw.extend([
        "lyrics",
        "lyric video",
        "lyrics video",
        "song lyrics",
        "music lyrics",
        "english lyrics",
        "new songs",
        "trending music",
    ])
    if extra_tags and isinstance(extra_tags, list):
        for t in extra_tags:
            clean = str(t).replace("#", "").strip()
            if clean:
                raw.append(clean)

    return _limit_youtube_tags(raw, max_chars=450)


def build_seo_description(
    song_title: str,
    artist_text: str,
    artists: list[str],
    album: str,
    year: str,
    genre: str,
    fun_fact: str,
    lyrics_text: str,
    tags: list[str],
    hashtags: list[str],
) -> str:
    # 1. Top Hashtags
    safe_hashtags = ["#winsomegin"]
    for h in hashtags:
        formatted = str(h).strip()
        if not formatted.startswith("#"):
            formatted = f"#{formatted}"
        safe_hashtags.append(formatted)
    safe_hashtags.extend([_tagify(song_title), _tagify(artist_text), "#Lyrics", "#LyricVideo"])
    top_hash_line = "  ".join(_dedupe(safe_hashtags)[:6])

    # 2. CTA & Header
    header = (
        f"{top_hash_line}\n\n"
        f"🎶 {song_title} - {artist_text} (Lyrics)\n\n"
        "🔥 Help us reach 1,000 subscribers!\n"
        "🔔 Subscribe and turn on notifications to never miss a release.\n"
        "👍🏽 Leave a like, comment, and share to support the channel!\n"
        "________________________________________________________________________\n"
    )

    # 3. Track Info Box
    info_lines = [
        f"🎵 Track  : {song_title}",
        f"🎤 Artist : {artist_text}",
    ]
    if album:
        info_lines.append(f"💿 Album  : {album}")
    if year:
        info_lines.append(f"📅 Year   : {year}")
    if genre:
        info_lines.append(f"🏷️ Genre  : {genre}")
    if fun_fact:
        info_lines.append(f"✨ Note   : {fun_fact}")
    info_block = "\n".join(info_lines) + "\n________________________________________________________________________\n"

    # 4. Search Keyword Tag Cloud
    tag_cloud_items = ["#winsomegin"]
    for t in tags[:15]:
        item = _tagify(t)
        if item:
            tag_cloud_items.append(item)
    tag_cloud = "📋 Tags: " + " ".join(_dedupe(tag_cloud_items)[:16]) + "\n\n"

    # 5. Full Lyrics
    lyrics_block = "🎤 Lyrics:\n" + (lyrics_text.strip() or "Lyrics not available.")

    full_desc = f"{header}\n{info_block}\n{tag_cloud}{lyrics_block}"

    # YouTube description max is 5000 UTF-8 bytes. Truncate safely at 4900 bytes if needed.
    encoded = full_desc.encode("utf-8")
    if len(encoded) <= 4900:
        return full_desc

    prefix = f"{header}\n{info_block}\n{tag_cloud}🎤 Lyrics:\n"
    prefix_len = len(prefix.encode("utf-8"))
    allowed_lyrics = max(100, 4880 - prefix_len)
    trimmed_lyrics = lyrics_text.encode("utf-8")[:allowed_lyrics].decode("utf-8", errors="ignore").rstrip()
    return f"{prefix}{trimmed_lyrics}\n\n[...]"


def generate_youtube_metadata(project_dir: Path | str) -> dict[str, Any]:
    """Generate high-performing YouTube metadata with mandatory Gemini AI enrichment."""
    project_path = Path(project_dir).resolve()
    # flat upload in project_path

    # 1. Read project info
    state_file = project_path / "project_state.json"
    state = json.loads(state_file.read_text(encoding="utf-8")) if state_file.is_file() else {}

    editor_file = project_path / "editor_project.json"
    editor_data = json.loads(editor_file.read_text(encoding="utf-8")) if editor_file.is_file() else {}

    song_title = (
        editor_data.get("intro_title_text")
        or state.get("title")
        or project_path.name
    )
    artist_text = (
        editor_data.get("intro_artist_text")
        or state.get("artist")
        or "Unknown Artist"
    )
    lyrics_text = _read_project_lyrics(project_path)
    artists = _split_artists(artist_text)

    print(f"[*] Calling Gemini AI for metadata enrichment ({song_title} by {artist_text})...")
    gemini_data = enrich_with_gemini(song_title, artist_text, lyrics_sample=lyrics_text)

    album = _clean_spaces(gemini_data.get("album", ""))
    year = _clean_spaces(gemini_data.get("year", ""))
    genre = _clean_spaces(gemini_data.get("genre", ""))
    extra_tags = gemini_data.get("extra_tags") or []
    hashtags = gemini_data.get("description_hashtags") or []
    fun_fact = _clean_spaces(gemini_data.get("fun_fact", ""))
    model_used = gemini_data.get("_model", "gemini")

    print(f"    [+] Gemini enriched via {model_used}: Year={year or 'N/A'}, Genre={genre or 'N/A'}, Tags={len(extra_tags)}")

    # 2. Build Title, Tags, Description
    title = build_seo_title(song_title, artist_text, album, year, genre)
    tags = build_seo_tags(song_title, artist_text, artists, extra_tags)
    description = build_seo_description(
        song_title,
        artist_text,
        artists,
        album,
        year,
        genre,
        fun_fact,
        lyrics_text,
        tags,
        hashtags,
    )

    metadata = {
        "title": title,
        "description": description,
        "tags": tags,
        "category_id": "10",  # Music
        "made_for_kids": False,
        "album": album,
        "year": year,
        "genre": genre,
        "fun_fact": fun_fact,
        "gemini_model": model_used,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    meta_path = project_path / "youtube_metadata.json"
    meta_path.write_text(json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"    [OK] YouTube metadata saved -> youtube_metadata.json")
    return metadata


def get_youtube_service():
    """Authenticate with YouTube Data API v3 using OAuth2 credentials."""
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    if not YOUTUBE_CLIENT_SECRET_PATH.is_file():
        raise FileNotFoundError(
            f"YouTube OAuth client secret file not found at: '{YOUTUBE_CLIENT_SECRET_PATH}'\n"
            "Download your OAuth client ID credentials from Google Cloud Console as 'youtube_client_secret.json'."
        )

    creds: Credentials | None = None
    if YOUTUBE_TOKEN_PATH.is_file():
        creds = Credentials.from_authorized_user_file(str(YOUTUBE_TOKEN_PATH), YOUTUBE_SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            print("[*] Refreshing YouTube OAuth token...")
            creds.refresh(Request())
        else:
            print("[*] Initiating YouTube OAuth browser authorization...")
            flow = InstalledAppFlow.from_client_secrets_file(
                str(YOUTUBE_CLIENT_SECRET_PATH), YOUTUBE_SCOPES
            )
            creds = flow.run_local_server(port=0)

        YOUTUBE_TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
        YOUTUBE_TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")

    return build("youtube", "v3", credentials=creds, cache_discovery=False)


def find_rendered_video(project_dir: Path) -> Path | None:
    final_video = project_dir / "final_video.mp4"
    if final_video.is_file() and final_video.stat().st_size > 0:
        return final_video

    for mp4 in project_dir.glob("*.mp4"):
        if mp4.stat().st_size > 0:
            return mp4
    return None


def find_project_thumbnail(project_dir: Path) -> Path | None:
    for candidate in [
        project_dir / "thumbnail.jpg",
        project_dir / "thumbnail.png",
        project_dir / "video_background.jpg",
    ]:
        if candidate.is_file() and candidate.stat().st_size > 0:
            return candidate
    return None


def upload_project_video(
    project_dir: Path | str,
    song_id: str | None = None,
    *,
    privacy_status: str = "public",
    publish_at: str | None = None,
) -> dict[str, Any]:
    """Full Stage 5 pipeline: generate Gemini metadata, upload video and thumbnail to YouTube."""
    from googleapiclient.http import MediaFileUpload

    project_path = Path(project_dir).resolve()
    # flat upload in project_path

    # 1. Ensure video exists
    video_path = find_rendered_video(project_path)
    if not video_path:
        raise FileNotFoundError(f"No rendered video found in {project_path}")

    video_size_mb = video_path.stat().st_size / (1024 * 1024)

    # 2. Generate or load metadata (with mandatory Gemini enrichment)
    meta_path = project_path / "youtube_metadata.json"
    if not meta_path.is_file():
        metadata = generate_youtube_metadata(project_path)
    else:
        metadata = json.loads(meta_path.read_text(encoding="utf-8"))

    # 3. Authenticate with YouTube API
    print("[*] Connecting to YouTube Data API...")
    youtube = get_youtube_service()

    # 4. Prepare insert body
    status_dict: dict[str, Any] = {
        "privacyStatus": privacy_status,
        "selfDeclaredMadeForKids": False,
    }
    if publish_at:
        status_dict["publishAt"] = publish_at
        status_dict["privacyStatus"] = "private"

    body = {
        "snippet": {
            "title": metadata["title"],
            "description": metadata["description"],
            "tags": metadata["tags"],
            "categoryId": metadata.get("category_id", "10"),
            "defaultLanguage": "en",
        },
        "status": status_dict,
    }

    # 5. Resumable Upload
    print(f"[*] Uploading video to YouTube ({video_path.name}, {video_size_mb:.1f} MB)...")
    media = MediaFileUpload(
        str(video_path),
        chunksize=8 * 1024 * 1024,
        resumable=True,
        mimetype="video/mp4",
    )
    insert_req = youtube.videos().insert(
        part="snippet,status",
        body=body,
        media_body=media,
    )

    response = None
    last_printed_progress = -1
    while response is None:
        status, response = insert_req.next_chunk()
        if status:
            prog_pct = int(status.progress() * 100)
            if prog_pct // 20 > last_printed_progress:
                last_printed_progress = prog_pct // 20
                print(f"    -> Upload progress: {prog_pct}%")

    video_id = response.get("id") if isinstance(response, dict) else None
    if not video_id:
        raise RuntimeError("YouTube API did not return a valid video ID.")

    video_url = f"https://www.youtube.com/watch?v={video_id}"
    print(f"[+] Video upload successful! Video ID: {video_id}")
    print(f"    URL: {video_url}")

    # 6. Upload Custom Thumbnail
    thumbnail_path = find_project_thumbnail(project_path)
    thumbnail_uploaded = False
    if thumbnail_path:
        try:
            print(f"[*] Setting custom video thumbnail from {thumbnail_path.name}...")
            thumb_media = MediaFileUpload(str(thumbnail_path), mimetype="image/jpeg")
            youtube.thumbnails().set(videoId=video_id, media_body=thumb_media).execute()
            thumbnail_uploaded = True
            print("    [OK] Custom thumbnail uploaded!")
        except Exception as exc:
            print(f"    [!] Warning: Thumbnail upload failed: {exc}")

    # 7. Write Upload Report
    now_str = datetime.now(timezone.utc).isoformat()
    report = {
        "ok": True,
        "video_id": video_id,
        "video_url": video_url,
        "title": metadata["title"],
        "privacy_status": status_dict["privacyStatus"],
        "publish_at": publish_at,
        "thumbnail_uploaded": thumbnail_uploaded,
        "video_size_mb": round(video_size_mb, 2),
        "uploaded_at": now_str,
    }
    report_path = project_path / "youtube_upload_report.json"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    # 8. Update Project State
    state_file = project_path / "project_state.json"
    if state_file.is_file():
        state = json.loads(state_file.read_text(encoding="utf-8"))
        state.update({
            "status": "uploaded",
            "youtube_video_id": video_id,
            "youtube_video_url": video_url,
            "uploaded_at": now_str,
        })
        state_file.write_text(json.dumps(state, indent=2), encoding="utf-8")

    # 9. Update Database Status
    if song_id:
        mark_song_status(song_id, "uploaded", project_dir=str(project_path))

    return report


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="EchoForge TubeHarbor: Gemini Metadata & YouTube Publisher")
    parser.add_argument("--project", required=True, help="Path to project folder")
    parser.add_argument("--metadata-only", action="store_true", help="Only generate Gemini metadata without uploading")
    parser.add_argument("--privacy", choices=["public", "unlisted", "private"], default="public", help="Video visibility")
    parser.add_argument("--song-id", default=None, help="Database song ID to mark as uploaded")
    args = parser.parse_args()

    project_dir = Path(args.project).resolve()
    if not project_dir.is_dir():
        print(f"[-] Error: Project directory not found: {project_dir}")
        return 1

    if args.metadata_only:
        generate_youtube_metadata(project_dir)
        return 0

    upload_project_video(project_dir, song_id=args.song_id, privacy_status=args.privacy)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

