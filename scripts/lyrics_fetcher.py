"""
lyrics_fetcher.py

Multi-tier lyrics fetcher with an LLM post-processor.

Changes
───────
• Bug 3: LLM formatter now OVERWRITES the source file in-place (keeping a
         backup as lyrics_original.*) instead of creating lyrics_clean.*.
         This ensures timestamp_processor.process_timestamps() always finds
         lyrics.lrc / lyrics.txt — the canonical paths it looks for.

CLI USAGE:
    python lyrics_fetcher.py fetch --title "Song" --artist "Artist" --workspace ./ws
    python lyrics_fetcher.py format --file path/to/lyrics.lrc
"""

import argparse
import os
import re
import shutil

import requests
import syncedlyrics
import lyricsgenius
from dotenv import load_dotenv

from lrc_sanitizer import sanitize_lrc
from utils import retry
from config import MAX_LINE_CHARS, LYRICS_MIN_LEFT
from logger import get_logger

log = get_logger(__name__)

load_dotenv()
GENIUS_TOKEN  = os.getenv("GENIUS_ACCESS_TOKEN")
ANTHROPIC_KEY = os.getenv("ANTHROPIC_API_KEY")

LLM_MAX_LINE = 35
LLM_MODEL    = "qwen2.5:7b"
LLM_ENDPOINT = "http://localhost:11434/api/generate"
LLM_TIMEOUT  = None 


# ═══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

def _is_valid_lrc(lrc_text: str) -> bool:
    return bool(re.search(r'\[\d{2}:\d{2}\.\d{2,3}\]', lrc_text))


def _contains_non_latin_words(text: str) -> bool:
    stripped = re.sub(r'\[\d{2}:\d{2}\.\d+\]', '', text)
    return bool(re.search(r'[^\x00-\x7F\u00C0-\u024F]{2,}', stripped))


def _is_latin_only(text: str) -> bool:
    return not bool(re.search(r'[^\x00-\x7F\u00C0-\u024F]{2,}', text))


def _lrc_to_plain_text(lrc_text: str) -> str:
    lines = []
    for line in lrc_text.split('\n'):
        cleaned = re.sub(r'\[\d{2}:\d{2}[.:]\d{2,3}\]', '', line).strip()
        if cleaned:
            lines.append(cleaned)
    return '\n'.join(lines)


def clean_genius_lyrics(raw: str) -> str:
    cleaned = re.sub(r'^\d+\s*Contributors?.*?Lyrics\n', '', raw, flags=re.IGNORECASE)
    cleaned = re.sub(r'^\[.*?\]\n?', '', cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r'\d*\s*Embed\s*$', '', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'\n{3,}', '\n\n', cleaned)
    return cleaned.strip()


def _is_fragment_line(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    if re.match(r'^[^a-zA-Z0-9]+$', stripped):
        return True
    if stripped.startswith(')'):
        return True
    if stripped[0].islower():
        return True
    meaningful = [w for w in stripped.split() if re.search(r'[a-zA-Z]', w)]
    return len(meaningful) <= 1


def normalize_lyrics_txt(raw: str) -> str:
    raw   = re.sub(r'([a-z])([A-Z])', r'\1\n\2', raw)
    lines = raw.split('\n')
    result: list[str] = []
    fragment_buffer: list[str] = []

    for line in lines:
        stripped = line.strip()
        if not stripped:
            if fragment_buffer:
                result.append(' '.join(fragment_buffer))
                fragment_buffer.clear()
            result.append('')
            continue
        if _is_fragment_line(stripped):
            fragment_buffer.append(stripped)
        else:
            if fragment_buffer:
                result.append((' '.join(fragment_buffer) + ' ' + stripped).strip())
                fragment_buffer.clear()
            else:
                result.append(stripped)

    if fragment_buffer:
        if result:
            for idx in range(len(result) - 1, -1, -1):
                if result[idx].strip():
                    result[idx] = result[idx] + ' ' + ' '.join(fragment_buffer)
                    break
            else:
                result.append(' '.join(fragment_buffer))
        else:
            result.append(' '.join(fragment_buffer))
        fragment_buffer.clear()

    i = 0
    while i < len(result):
        line = result[i]
        if not line.strip():
            i += 1
            continue
        if line.count('(') > line.count(')'):
            j = i + 1
            while j < len(result) and not result[j].strip():
                j += 1
            if j < len(result):
                result[i] = line + ' ' + result[j]
                result.pop(j)
                continue
        i += 1

    result      = _split_long_lines(result)
    normalized  = re.sub(r'\n{3,}', '\n\n', '\n'.join(result))
    return normalized.strip()


_MIN_LEFT = LYRICS_MIN_LEFT


def _find_best_break(s: str) -> int:
    for m in re.finditer(r'\)\s*', s):
        pos = m.end()
        if pos < _MIN_LEFT:
            continue
        if pos <= MAX_LINE_CHARS:
            return pos
        if pos <= MAX_LINE_CHARS + 10 and len(s) - pos > 10:
            return pos
        break
    for m in re.finditer(r'[,\.!\?]\s+', s):
        pos = m.end()
        if pos < _MIN_LEFT:
            continue
        if pos <= MAX_LINE_CHARS + 5:
            return pos
        break
    space = s.rfind(' ', _MIN_LEFT, MAX_LINE_CHARS)
    return space + 1 if space != -1 else MAX_LINE_CHARS


def _split_long_lines(lines: list) -> list:
    out = []
    for line in lines:
        if not line.strip() or len(line) <= MAX_LINE_CHARS:
            out.append(line)
            continue
        remaining = line
        while len(remaining) > MAX_LINE_CHARS:
            best      = _find_best_break(remaining)
            piece     = remaining[:best].strip()
            remaining = remaining[best:].strip()
            if len(piece) > MAX_LINE_CHARS:
                space = piece.rfind(' ', _MIN_LEFT, MAX_LINE_CHARS)
                if space != -1:
                    remaining = piece[space:].strip() + (' ' + remaining if remaining else '')
                    piece     = piece[:space].strip()
            out.append(piece)
        if remaining:
            out.append(remaining)
    return out


# ═══════════════════════════════════════════════════════════════════════════════
# LLM LINE-LENGTH FORMATTER
# ═══════════════════════════════════════════════════════════════════════════════

def _needs_formatting(text: str) -> bool:
    for line in text.split('\n'):
        stripped = re.sub(r'\[\d{2}:\d{2}[.:]\d{2,3}\]', '', line).strip()
        if len(stripped) > LLM_MAX_LINE:
            return True
    return False


def _call_llm_formatter(raw_content: str, file_type: str) -> str | None:
    if file_type == "lrc":
        format_rules = (
            "The input is an LRC file with lines like `[mm:ss.cc] lyric text`.\n"
            "Rules:\n"
            "1. NEVER modify or remove timestamps — they must remain exactly as-is.\n"
            "2. If a line's TEXT portion (after the timestamp) exceeds 35 characters, "
            "   split it at the best natural semantic or grammatical pause for the "
            "   language of the text by inserting a newline `\\n` WITHIN the text "
            "   (not before the timestamp). The resulting sub-lines inherit the same timestamp.\n"
            "3. Lines already ≤35 characters must be output unchanged.\n"
            "4. Output ONLY the reformatted LRC — no explanations, no Markdown fences."
        )
    else:
        format_rules = (
            "The input is plain-text lyrics (one line per lyric phrase).\n"
            "Rules:\n"
            "1. If a line exceeds 35 characters, split it at the best natural "
            "   semantic or grammatical pause for the language by inserting `\\n`.\n"
            "2. Lines already ≤35 characters must be output unchanged.\n"
            "3. Output ONLY the reformatted lyrics — no explanations."
        )

    prompt = (
        f"You are a lyrics formatter. {format_rules}\n\n"
        f"--- INPUT ---\n{raw_content}\n--- END INPUT ---"
    )

    body = {
        "model":  LLM_MODEL,
        "prompt": prompt,
        "stream": False
    }

    try:
        log.info("🤖 Calling local LLM formatter (model: %s)...", LLM_MODEL)
        log.info("⏳ Processing song... (No time limit, this may take a while depending on your hardware)")
        
        resp = requests.post(LLM_ENDPOINT, json=body, timeout=LLM_TIMEOUT)
        resp.raise_for_status()
        
        result = resp.json().get("response", "").strip()
        log.info("✅ LLM formatter returned %d chars.", len(result))
        return result
        
    except requests.exceptions.ConnectionError:
        log.error("❌ Failed to connect to local LLM. Is Ollama running (`ollama serve`)?")
        return None
    except Exception as exc:
        log.warning("⚠️ Local LLM formatter failed: %s — using original content.", exc)
        return None


def llm_format_lyrics(src_path: str) -> str:
    """
    Run the LLM line-length formatter on *src_path* (.lrc or .txt).

    Bug 3 fix — overwrites the source file in-place so that
    timestamp_processor.process_timestamps() always finds the canonical
    lyrics.lrc / lyrics.txt paths.  A backup is saved as
    lyrics_original.lrc / lyrics_original.txt before overwriting.

    Returns the path of the (possibly overwritten) file.
    If the file needs no formatting, or the LLM call fails, the original
    file is returned unchanged (no backup written in that case).
    """
    ext       = os.path.splitext(src_path)[1].lower()
    file_type = "lrc" if ext == ".lrc" else "txt"

    with open(src_path, "r", encoding="utf-8") as fh:
        original = fh.read()

    if not _needs_formatting(original):
        log.info("✅ No long lines found — LLM formatter not needed.")
        return src_path

    log.info("📏 Long lines detected — sending to LLM formatter...")
    formatted = _call_llm_formatter(original, file_type)

    if not formatted:
        log.warning("⚠️  LLM formatter returned nothing — keeping original.")
        return src_path

    # Sanity check: output must not be drastically shorter than input
    if len(formatted) < len(original) * 0.5:
        log.warning(
            "⚠️  LLM output suspiciously short (%d vs %d chars) — discarding.",
            len(formatted), len(original),
        )
        return src_path

    # Write backup BEFORE overwriting
    backup_path = src_path.replace(ext, f"_original{ext}")
    shutil.copy2(src_path, backup_path)
    log.info("💾 Backup saved: %s", backup_path)

    # Overwrite in-place — downstream modules find the same canonical path
    with open(src_path, "w", encoding="utf-8") as fh:
        fh.write(formatted)
    log.info("✅ Formatted lyrics written back to: %s", src_path)

    return src_path


# ═══════════════════════════════════════════════════════════════════════════════
# RETRY-WRAPPED NETWORK PRIMITIVES
# ═══════════════════════════════════════════════════════════════════════════════

@retry(max_attempts=3, delay=8, backoff=2, exceptions=(Exception,))
def _do_genius_search(genius, title: str, artist: str | None = None):
    if artist:
        return genius.search_song(title, artist)
    return genius.search_song(title)


@retry(max_attempts=3, delay=8, backoff=2, exceptions=(Exception,))
def _do_syncedlyrics_search(query: str, lrc_path: str) -> str | None:
    return syncedlyrics.search(query, save_path=lrc_path)


# ═══════════════════════════════════════════════════════════════════════════════
# GENIUS ROMANIZED FETCH
# ═══════════════════════════════════════════════════════════════════════════════

def _try_genius_search(genius, title: str, artist: str) -> str | None:
    romanized_title = f"{title} (Romanized)"
    log.info("   🔍 Trying: '%s - %s'", artist, romanized_title)
    try:
        song = _do_genius_search(genius, romanized_title, artist)
        if not song or not song.lyrics:
            return None
        clean = clean_genius_lyrics(song.lyrics)
        if not _is_latin_only(clean):
            log.warning("   ⚠️ Latin validation failed — skipping.")
            return None
        return normalize_lyrics_txt(clean)
    except Exception as exc:
        log.warning("   ⚠️ Search failed: %s", exc)
        return None


def _fetch_genius_romanized(title: str, artist: str) -> str | None:
    if not GENIUS_TOKEN:
        log.warning("⚠️ GENIUS_ACCESS_TOKEN not set.")
        return None

    genius      = lyricsgenius.Genius(GENIUS_TOKEN, verbose=False, skip_non_songs=True)
    all_artists = [
        a.strip()
        for a in re.split(r'\s*[&,/]\s*|\s+ft\.?\s+|\s+x\s+', artist, flags=re.IGNORECASE)
        if a.strip()
    ]
    first_artist = all_artists[0]

    result = _try_genius_search(genius, title, first_artist)
    if result:
        return result
    for alt in all_artists[1:]:
        result = _try_genius_search(genius, title, alt)
        if result:
            return result
    try:
        song = _do_genius_search(genius, f"{title} (Romanized)")
        if song and song.lyrics:
            clean = clean_genius_lyrics(song.lyrics)
            if _is_latin_only(clean):
                return normalize_lyrics_txt(clean)
    except Exception:
        pass
    try:
        song = _do_genius_search(genius, title, first_artist)
        if song and song.lyrics:
            clean = clean_genius_lyrics(song.lyrics)
            if _is_latin_only(clean):
                return normalize_lyrics_txt(clean)
    except Exception:
        pass

    log.error("   ❌ All Genius strategies exhausted.")
    return None


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN FETCH FUNCTION
# ═══════════════════════════════════════════════════════════════════════════════

def fetch_lyrics(title: str, artist: str, workspace_dir: str):
    """
    Tier 1: syncedlyrics → valid .lrc, fully Latin → SYNCED
    Tier 2: Genius (Romanized) plain text → PLAIN
    Tier 3: Nothing worked → NONE

    After a successful fetch, the file is passed through the LLM formatter
    which overwrites it in-place (Bug 3 fix) so downstream modules always
    find lyrics.lrc / lyrics.txt at their canonical paths.

    Returns: (status, file_path)
    """
    search_query = f"{title} {artist}"
    lrc_path     = os.path.join(workspace_dir, "lyrics.lrc")
    txt_path     = os.path.join(workspace_dir, "lyrics.txt")

    # ── TIER 1: Synced Lyrics ────────────────────────────────────────────────
    log.info("\n[Tier 1] Searching synced .lrc: '%s'", search_query)
    try:
        lrc_text = _do_syncedlyrics_search(search_query, lrc_path)

        if lrc_text and _is_valid_lrc(lrc_text):
            log.info("✅ Synced lyrics found!")
            sanitize_lrc(lrc_path)
            with open(lrc_path, "r", encoding="utf-8") as fh:
                lrc_text = fh.read()

            if not _contains_non_latin_words(lrc_text):
                log.info("✅ Fully Latin — saving plain-text copy.")
                plain = _lrc_to_plain_text(lrc_text)
                with open(txt_path, "w", encoding="utf-8") as fh:
                    fh.write(plain)

                # Bug 3 fix: overwrites lrc_path in-place; backup is lyrics_original.lrc
                llm_format_lyrics(lrc_path)
                return "SYNCED", lrc_path

            log.info("🌐 Non-Latin words detected — discarding LRC, falling to Genius.")
            if os.path.exists(lrc_path):
                os.remove(lrc_path)
        else:
            log.warning("⚠️ No valid timestamped LRC found.")
            if os.path.exists(lrc_path):
                os.remove(lrc_path)

    except Exception as exc:
        log.warning("⚠️ Synced fetch failed: %s", exc)

    # ── TIER 2: Genius Romanized ─────────────────────────────────────────────
    log.info("\n[Tier 2] Fetching Genius romanized plain text...")
    genius_text = _fetch_genius_romanized(title, artist)

    if genius_text:
        with open(txt_path, "w", encoding="utf-8") as fh:
            fh.write(genius_text)
        log.info("✅ Romanized lyrics saved: %s", txt_path)

        # Bug 3 fix: overwrites txt_path in-place; backup is lyrics_original.txt
        llm_format_lyrics(txt_path)
        return "PLAIN", txt_path

    # ── TIER 3: Manual upload required ───────────────────────────────────────
    log.error("❌ All automated fetches failed. Manual upload required.")
    return "NONE", None


# ─── CLI ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser    = argparse.ArgumentParser(description="EchoForge Lyrics Fetcher")
    subparsers = parser.add_subparsers(dest="command")

    fetch_cmd = subparsers.add_parser("fetch", help="Fetch lyrics for a song")
    fetch_cmd.add_argument("--title",     required=True)
    fetch_cmd.add_argument("--artist",    required=True)
    fetch_cmd.add_argument("--workspace", required=True)

    fmt_cmd = subparsers.add_parser("format", help="Run LLM formatter on an existing file")
    fmt_cmd.add_argument("--file", required=True, help="Path to .lrc or .txt file")

    args = parser.parse_args()

    if args.command == "fetch":
        status, path = fetch_lyrics(args.title, args.artist, args.workspace)
        print(f"\nStatus : {status}")
        print(f"File   : {path}")
    elif args.command == "format":
        out = llm_format_lyrics(args.file)
        print(f"Formatted file: {out}")
    else:
        parser.print_help()