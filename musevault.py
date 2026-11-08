from __future__ import annotations

import html
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus

import requests
import yt_dlp

from paths import PROJECTS_DIR, ROOT_DIR
from songscout import mark_song_status, slugify


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def load_env() -> None:
    """Load environment variables from .env in project or parent root."""
    try:
        from dotenv import load_dotenv

        for folder in [Path.cwd(), ROOT_DIR, ROOT_DIR.parent]:
            env_file = folder / ".env"
            if env_file.exists():
                load_dotenv(env_file)
                break
    except ImportError:
        pass


def get_next_project_dir(title: str, artist: str) -> Path:
    """Determine the next sequential project folder (e.g. projects/0001_title_artist)."""
    PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
    existing_nums = []
    for p in PROJECTS_DIR.iterdir():
        if p.is_dir():
            match = re.match(r"^(\d{4})_", p.name)
            if match:
                existing_nums.append(int(match.group(1)))

    next_num = max(existing_nums, default=0) + 1
    folder_name = f"{next_num:04d}_{slugify(title)}_{slugify(artist)}"
    project_dir = PROJECTS_DIR / folder_name

    for sub in ["audio", "lyrics", "images", "renders"]:
        (project_dir / sub).mkdir(parents=True, exist_ok=True)

    return project_dir


def download_audio(youtube_url: str, audio_dir: Path) -> Path | None:
    """Download audio track from YouTube and normalize to source_audio.m4a."""
    target_path = audio_dir / "source_audio.m4a"
    if target_path.exists() and target_path.stat().st_size > 1000:
        return target_path

    print(f"[*] Downloading audio from: {youtube_url}")
    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": str(audio_dir / "source_audio.%(ext)s"),
        "noplaylist": True,
        "quiet": True,
        "js_runtimes": {"node": {}},
        "extractor_args": {
            "youtube": {
                "player_client": ["android", "ios", "mweb"],
            }
        },
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "m4a",
                "preferredquality": "192",
            }
        ],
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([youtube_url])

        if target_path.exists() and target_path.stat().st_size > 1000:
            return target_path

        # Fallback check if saved under another extension
        for f in audio_dir.glob("source_audio.*"):
            if f.stat().st_size > 1000:
                return f
    except Exception as exc:
        print(f"[!] Audio download failed: {exc}")
    return None


# ==============================================================================
# Lyrics Fetching: Tier 1 (LRCLIB), Tier 2 (Genius), Tier 3 (Pop-Up Dialogue)
# ==============================================================================


def fetch_from_lrclib(title: str, artist: str, lyrics_dir: Path) -> dict[str, bool]:
    """Tier 1: Query LRCLIB for synced LRC or plain lyrics."""
    url = f"https://lrclib.net/api/search?track_name={quote_plus(title)}&artist_name={quote_plus(artist)}"
    result = {"synced": False, "plain": False}

    try:
        res = requests.get(url, timeout=12, headers={"User-Agent": "EchoForge/1.0"})
        if res.status_code == 200:
            candidates = res.json()
            if candidates:
                best = candidates[0]
                synced_lyrics = best.get("syncedLyrics")
                plain_lyrics = best.get("plainLyrics")

                if synced_lyrics:
                    (lyrics_dir / "lyrics.lrc").write_text(synced_lyrics, encoding="utf-8")
                    result["synced"] = True

                if plain_lyrics:
                    (lyrics_dir / "lyrics.txt").write_text(plain_lyrics, encoding="utf-8")
                    result["plain"] = True
    except Exception:
        pass

    return result


def fetch_from_genius(title: str, artist: str, lyrics_dir: Path) -> dict[str, bool]:
    """Tier 2: Search Genius API and scrape lyrics."""
    load_env()
    token = os.getenv("GENIUS_ACCESS_TOKEN")
    result = {"synced": False, "plain": False}
    if not token:
        return result

    try:
        search_res = requests.get(
            "https://api.genius.com/search",
            params={"q": f"{title} {artist}".strip()},
            headers={"Authorization": f"Bearer {token}", "User-Agent": "EchoForge/1.0"},
            timeout=15,
        )
        if search_res.status_code != 200:
            return result

        hits = search_res.json().get("response", {}).get("hits", [])
        if not hits or not hits[0].get("result", {}).get("url"):
            return result

        song_url = hits[0]["result"]["url"]
        page_res = requests.get(song_url, timeout=15, headers={"User-Agent": "Mozilla/5.0 EchoForge/1.0"})
        if page_res.status_code != 200:
            return result

        # Extract blocks from data-lyrics-container
        blocks = re.findall(
            r'<div[^>]+data-lyrics-container="true"[^>]*>(.*?)</div>',
            page_res.text,
            flags=re.I | re.S,
        )
        if not blocks:
            return result

        combined = "\n".join(blocks)
        cleaned = re.sub(r"<br\s*/?>", "\n", combined, flags=re.I)
        cleaned = re.sub(r"<[^>]+>", "", cleaned)
        cleaned = html.unescape(cleaned)

        lines = []
        for line in cleaned.splitlines():
            line = line.strip()
            low = line.lower()
            if not line or low.startswith(("contributors", "translations", "you might also like", "embed")):
                continue
            lines.append(line)

        final_lyrics = "\n".join(lines).strip()
        if len(final_lyrics) > 20:
            (lyrics_dir / "lyrics.txt").write_text(final_lyrics, encoding="utf-8")
            result["plain"] = True
    except Exception:
        pass

    return result


def prompt_lyrics_popup(title: str, artist: str, lyrics_dir: Path) -> dict[str, bool]:
    """Tier 3: Pop-up GUI dialogue box allowing the user to paste formatted lyrics."""
    import tkinter as tk
    from tkinter import scrolledtext

    result = {"synced": False, "plain": False}
    pasted_content = ""

    root = tk.Tk()
    root.title(f"EchoForge — Paste Lyrics: {title}")
    root.geometry("640x520")
    root.attributes("-topmost", True)

    tk.Label(
        root,
        text=f"Lyrics not found automatically.\nPlease paste lyrics for:\n'{title}' by {artist}",
        font=("Arial", 11, "bold"),
        pady=10,
    ).pack()

    tk.Label(
        root,
        text="Supported: Plain text OR [mm:ss.xx] timestamped LRC. Click Save when ready.",
        font=("Arial", 9),
        fg="#444",
    ).pack()

    text_area = scrolledtext.ScrolledText(root, wrap=tk.WORD, font=("Consolas", 10), width=70, height=17)
    text_area.pack(padx=15, pady=8, fill=tk.BOTH, expand=True)
    text_area.focus_set()

    btn_frame = tk.Frame(root)
    btn_frame.pack(pady=10)

    def on_save() -> None:
        nonlocal pasted_content
        pasted_content = text_area.get("1.0", tk.END).strip()
        root.destroy()

    def on_skip() -> None:
        root.destroy()

    tk.Button(
        btn_frame,
        text="Save & Continue",
        command=on_save,
        bg="#2e7d32",
        fg="white",
        font=("Arial", 10, "bold"),
        padx=14,
        pady=4,
    ).pack(side=tk.LEFT, padx=10)

    tk.Button(btn_frame, text="Skip", command=on_skip, font=("Arial", 10), padx=10, pady=4).pack(
        side=tk.LEFT, padx=10
    )

    root.mainloop()

    if pasted_content:
        # Check if text contains timestamp tags like [00:12.34]
        has_timestamps = bool(re.search(r"\[\d{2}:\d{2}", pasted_content))
        if has_timestamps:
            (lyrics_dir / "lyrics.lrc").write_text(pasted_content, encoding="utf-8")
            result["synced"] = True

            # Also generate plain lyrics by stripping timestamps
            plain = re.sub(r"\[\d{2}:\d{2}(?:\.\d{2,3})?\]", "", pasted_content)
            plain = "\n".join(l.strip() for l in plain.splitlines() if l.strip())
            (lyrics_dir / "lyrics.txt").write_text(plain, encoding="utf-8")
            result["plain"] = True
        else:
            (lyrics_dir / "lyrics.txt").write_text(pasted_content, encoding="utf-8")
            result["plain"] = True

    return result


def resolve_lyrics(title: str, artist: str, lyrics_dir: Path) -> dict[str, Any]:
    """Cascade through Tier 1 (LRCLIB), Tier 2 (Genius), and Tier 3 (Pop-up dialog)."""
    # 1. LRCLIB
    print(f"[*] [Tier 1] Checking LRCLIB for '{title}'...")
    res = fetch_from_lrclib(title, artist, lyrics_dir)
    if res["synced"]:
        return {"source": "lrclib", "status": "synced", "path": "lyrics.lrc"}
    if res["plain"]:
        return {"source": "lrclib", "status": "plain", "path": "lyrics.txt"}

    # 2. Genius API
    print(f"[*] [Tier 2] LRCLIB empty. Checking Genius API for '{title}'...")
    res = fetch_from_genius(title, artist, lyrics_dir)
    if res["plain"]:
        return {"source": "genius", "status": "plain", "path": "lyrics.txt"}

    # 3. Pop-up Dialogue
    print(f"[*] [Tier 3] No online lyrics found. Opening Pop-Up dialogue box...")
    res = prompt_lyrics_popup(title, artist, lyrics_dir)
    if res["synced"]:
        return {"source": "popup_manual", "status": "synced", "path": "lyrics.lrc"}
    if res["plain"]:
        return {"source": "popup_manual", "status": "plain", "path": "lyrics.txt"}

    return {"source": "none", "status": "missing", "path": None}


def download_thumbnail(thumbnail_url: str | None, images_dir: Path) -> Path | None:
    """Download the YouTube video thumbnail image."""
    if not thumbnail_url:
        return None

    target = images_dir / "thumbnail.jpg"
    try:
        res = requests.get(thumbnail_url, timeout=15)
        if res.status_code == 200:
            target.write_bytes(res.content)
            return target
    except Exception:
        pass
    return None


def collect_project_assets(song: dict[str, Any]) -> Path:
    """Initialize the project and download all needed assets."""
    title = song["title"]
    artist = song["artist"]
    youtube_url = song.get("youtube_url")

    # 1. Project folder
    project_dir = get_next_project_dir(title, artist)
    print(f"\n[+] Created project folder: {project_dir.name}")

    # 2. Audio
    if youtube_url:
        audio_file = download_audio(youtube_url, project_dir)
        if audio_file:
            print(f"    [OK] Audio downloaded -> source_audio.m4a")

    # 3. Multi-tier Lyrics Collection
    lyrics_info = resolve_lyrics(title, artist, project_dir)
    if lyrics_info["status"] != "missing":
        print(f"    [OK] Lyrics secured via {lyrics_info['source'].upper()} -> {lyrics_info['path']}")
    else:
        print(f"    [!] No lyrics available yet (Stage 3 will transcribe from audio)")

    # 4. Thumbnail
    thumb_file = download_thumbnail(song.get("thumbnail_url"), project_dir)
    if thumb_file:
        print(f"    [OK] Thumbnail downloaded -> thumbnail.jpg")

    # 5. Save state
    state = {
        "song_id": song["id"],
        "title": title,
        "artist": artist,
        "youtube_url": youtube_url,
        "lyrics_source": lyrics_info["source"],
        "lyrics_status": lyrics_info["status"],
        "status": "assets_ready",
        "created_at": now_iso(),
    }
    (project_dir / "project_state.json").write_text(json.dumps(state, indent=2), encoding="utf-8")

    # 6. Update database status
    mark_song_status(song["id"], "assets_ready", project_dir=str(project_dir))

    return project_dir