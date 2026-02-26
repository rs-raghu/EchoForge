import os
import re
import syncedlyrics
import lyricsgenius
from dotenv import load_dotenv

load_dotenv()
GENIUS_TOKEN = os.getenv("GENIUS_ACCESS_TOKEN")


# ============================================================
# HELPERS
# ============================================================

def _is_valid_lrc(lrc_text: str) -> bool:
    """Validates that the .lrc content actually contains timestamps."""
    return bool(re.search(r'\[\d{2}:\d{2}\.\d{2,3}\]', lrc_text))


def _contains_non_latin_words(text: str) -> bool:
    """
    Lenient check — True only if there are full non-Latin WORDS.
    Ignores stray chars like (ah), accented letters (é, ñ), punctuation.
    A 'non-Latin word' = 2+ consecutive non-Latin characters.
    """
    stripped = re.sub(r'\[\d{2}:\d{2}\.\d+\]', '', text)
    return bool(re.search(r'[^\x00-\x7F\u00C0-\u024F]{2,}', stripped))


def _is_latin_only(text: str) -> bool:
    """Strict check — True if text has NO non-Latin words."""
    return not bool(re.search(r'[^\x00-\x7F\u00C0-\u024F]{2,}', text))


def clean_genius_lyrics(raw_lyrics: str) -> str:
    """
    Strips all Genius junk:
    - '3 Contributors Song Name Lyrics' header
    - Section headers like [Verse 1], [Chorus], [Verse: Rumi, Zoey, Mira, All]
    - Trailing 'Embed' / '5Embed'
    - Collapsing extra blank lines
    """
    # Remove "X Contributors Title Lyrics" header line
    cleaned = re.sub(r'^\d+\s*Contributors?.*?Lyrics\n', '', raw_lyrics, flags=re.IGNORECASE)
    # Remove ALL section headers e.g. [Verse 1], [Chorus], [Bridge: Name, Name]
    cleaned = re.sub(r'^\[.*?\]\n?', '', cleaned, flags=re.MULTILINE)
    # Remove trailing Embed with optional number
    cleaned = re.sub(r'\d*\s*Embed\s*$', '', cleaned, flags=re.IGNORECASE)
    # Collapse multiple blank lines into one
    cleaned = re.sub(r'\n{3,}', '\n\n', cleaned)
    return cleaned.strip()


def _is_fragment_line(line: str) -> bool:
    """
    Returns True if this line is a fragment that should be merged
    with adjacent lines rather than treated as a standalone lyric line.

    Fragment patterns:
      - Just punctuation or parentheses (e.g. ")", "(", "...")
      - A single meaningful word (e.g. "Ah", "duwojin", "ap")
      - Starts with a lowercase letter (continuation of previous line)
      - Starts with a closing paren ")" (continuation from line that had "(" unclosed)
    """
    stripped = line.strip()
    if not stripped:
        return False

    # Just punctuation / parentheses / symbols — no letters or digits
    if re.match(r'^[^a-zA-Z0-9]+$', stripped):
        return True

    # Starts with closing paren → it's a continuation of the previous line
    if stripped.startswith(')'):
        return True

    # Starts with lowercase → it's a continuation
    if stripped[0].islower():
        return True

    # Count meaningful words (contain at least one letter)
    meaningful = [w for w in stripped.split() if re.search(r'[a-zA-Z]', w)]
    if len(meaningful) <= 1:
        return True

    return False


def normalize_lyrics_txt(raw: str) -> str:
    """
    Fixes common problems in Genius-scraped lyrics:

    1.  camelCase concatenations ("tooWildBut") → split into two lines
    2.  Fragment joining: lines that are continuations (lowercase start, ")"
        start, single-word, pure-punctuation) are PREPENDED to the next
        non-fragment line — NOT emitted as a standalone line.
    3.  Unmatched open-parenthesis lines are merged with the next line so
        that split ad-libs like "( Ah" / ") Given the throne" recombine.
    4.  Blank lines (section separators) are preserved.
    """
    # Step 1: Fix camelCase concatenations (missing newline between two lines)
    raw = re.sub(r'([a-z])([A-Z])', r'\1\n\2', raw)

    lines = raw.split('\n')
    result = []
    fragment_buffer: list[str] = []

    for line in lines:
        stripped = line.strip()

        if not stripped:
            # Blank line = section boundary
            # Orphaned fragments at a section break get their own line
            if fragment_buffer:
                result.append(' '.join(fragment_buffer))
                fragment_buffer.clear()
            result.append('')
            continue

        if _is_fragment_line(stripped):
            # Accumulate — will be prepended to the next non-fragment
            fragment_buffer.append(stripped)
        else:
            # Non-fragment: prepend any queued fragments to THIS line
            if fragment_buffer:
                combined = ' '.join(fragment_buffer) + ' ' + stripped
                fragment_buffer.clear()
                result.append(combined.strip())
            else:
                result.append(stripped)

    # End of file — flush any remaining fragments onto the last line
    if fragment_buffer:
        if result:
            # Find last non-blank line and append to it
            for idx in range(len(result) - 1, -1, -1):
                if result[idx].strip():
                    result[idx] = result[idx] + ' ' + ' '.join(fragment_buffer)
                    break
            else:
                result.append(' '.join(fragment_buffer))
        else:
            result.append(' '.join(fragment_buffer))
        fragment_buffer.clear()

    # Step 2: Merge lines that have unmatched opening parentheses with the next
    # non-blank line (handles ad-libs split across lines like "I believe (" / "Ah)")
    i = 0
    while i < len(result):
        line = result[i]
        if not line.strip():
            i += 1
            continue
        opens  = line.count('(')
        closes = line.count(')')
        if opens > closes:
            # Find the next non-blank line to absorb
            j = i + 1
            while j < len(result) and not result[j].strip():
                j += 1
            if j < len(result):
                result[i] = line + ' ' + result[j]
                result.pop(j)
                # Don't advance i — recheck in case the merged line still has open paren
                continue
        i += 1

    # Step 3: Split any lines that are still too long
    result = _split_long_lines(result)

    # Clean up: collapse consecutive blank lines
    normalized = re.sub(r'\n{3,}', '\n\n', '\n'.join(result))
    return normalized.strip()


# ============================================================
# LINE-LENGTH SPLITTER
# ============================================================

MAX_LINE_CHARS = 58  # comfortable lyric line width
_MIN_LEFT      = 20  # never split within the first 20 chars


def _find_best_break(s: str) -> int:
    """
    Returns the character index at which to split string s.

    Priority:
      1. FIRST closing ')' that is >= _MIN_LEFT chars in AND results in a
         left piece <= MAX_LINE_CHARS.  A +10 slack allows a slightly-over
         paren to win over a forced word-break — but only when the remainder
         is non-trivial (> 10 chars) so we don't produce orphan tokens.
      2. FIRST punctuation (, . ! ?) that keeps the left piece <= MAX+5.
      3. Last word boundary at or before MAX_LINE_CHARS.
    """
    # Priority 1 — first valid closing paren
    for m in re.finditer(r'\)\s*', s):
        pos = m.end()
        if pos < _MIN_LEFT:
            continue
        if pos <= MAX_LINE_CHARS:
            return pos
        if pos <= MAX_LINE_CHARS + 10 and len(s) - pos > 10:
            return pos
        break   # past tolerance — give up on paren breaks

    # Priority 2 — first punctuation break
    for m in re.finditer(r'[,\.!\?]\s+', s):
        pos = m.end()
        if pos < _MIN_LEFT:
            continue
        if pos <= MAX_LINE_CHARS + 5:
            return pos
        break

    # Priority 3 — last word boundary
    space = s.rfind(' ', _MIN_LEFT, MAX_LINE_CHARS)
    return space + 1 if space != -1 else MAX_LINE_CHARS


def _split_long_lines(lines: list) -> list:
    """
    Splits any line exceeding MAX_LINE_CHARS at the best natural break point,
    looping until every piece fits.  Handles lines with multiple ad-libs like
    "A ( Ah ) B ( Hah ) C D E F G" by always taking the FIRST valid break.
    """
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

            # Safety: if the piece is still over-limit (paren was at MAX+9),
            # force a word-boundary split before emitting.
            if len(piece) > MAX_LINE_CHARS:
                space = piece.rfind(' ', _MIN_LEFT, MAX_LINE_CHARS)
                if space != -1:
                    remaining = piece[space:].strip() + (' ' + remaining if remaining else '')
                    piece = piece[:space].strip()

            out.append(piece)

        if remaining:
            out.append(remaining)

    return out


# ============================================================
# GENIUS ROMANIZED FETCH
# ============================================================

def _try_genius_search(genius, title: str, artist: str) -> str | None:
    """
    Single Genius search attempt for '{artist} - {title} (Romanized)'.
    Returns normalized lyrics string or None.
    """
    romanized_title = f"{title} (Romanized)"
    print(f"   🔍 Trying: '{artist} - {romanized_title}'")
    try:
        song = genius.search_song(romanized_title, artist)
        if not song or not song.lyrics:
            return None
        clean = clean_genius_lyrics(song.lyrics)
        if not _is_latin_only(clean):
            print(f"   ⚠️ Result failed Latin validation — skipping.")
            return None
        normalized = normalize_lyrics_txt(clean)
        print(f"   ✅ Found and validated!")
        return normalized
    except Exception as e:
        print(f"   ⚠️ Search failed: {e}")
        return None


def _fetch_genius_romanized(title: str, artist: str) -> str | None:
    """
    Searches Genius for '{title} (Romanized)' using multiple artist fallbacks.

    Strategy (tries each until one succeeds):
      1. First artist only          — "Shashwat Sachdev"
      2. All individual artists     — "Madhubanti Bagchi", "Jasmine Sandlas", ...
      3. Title-only search          — artist field left empty so Genius picks
                                      the best match regardless of artist name
      4. Plain (non-romanized) title with first artist — last resort fallback
         for songs that may be listed without the (Romanized) suffix

    Validates every result is Latin-only before accepting it.
    Returns clean, normalized lyrics string or None.
    """
    if not GENIUS_TOKEN:
        print("⚠️ GENIUS_ACCESS_TOKEN not found in .env.")
        return None

    genius = lyricsgenius.Genius(GENIUS_TOKEN, verbose=False, skip_non_songs=True)

    # Split the full artist string into individual names
    all_artists = [
        a.strip()
        for a in re.split(r'\s*[&,/]\s*|\s+ft\.?\s+|\s+x\s+', artist, flags=re.IGNORECASE)
        if a.strip()
    ]
    first_artist = all_artists[0]

    # --- Attempt 1: first artist (original behaviour) ---
    result = _try_genius_search(genius, title, first_artist)
    if result:
        return result

    # --- Attempt 2: each remaining individual artist ---
    for alt_artist in all_artists[1:]:
        result = _try_genius_search(genius, title, alt_artist)
        if result:
            return result

    # --- Attempt 3: title-only (Genius picks best match) ---
    print(f"   🔍 Trying title-only search: '{title} (Romanized)'")
    try:
        song = genius.search_song(f"{title} (Romanized)")
        if song and song.lyrics:
            clean = clean_genius_lyrics(song.lyrics)
            if _is_latin_only(clean):
                print(f"   ✅ Title-only search succeeded!")
                return normalize_lyrics_txt(clean)
            else:
                print(f"   ⚠️ Title-only result failed Latin validation.")
    except Exception as e:
        print(f"   ⚠️ Title-only search failed: {e}")

    # --- Attempt 4: plain title (no Romanized suffix) with first artist ---
    print(f"   🔍 Trying plain title (no Romanized suffix): '{first_artist} - {title}'")
    try:
        song = genius.search_song(title, first_artist)
        if song and song.lyrics:
            clean = clean_genius_lyrics(song.lyrics)
            if _is_latin_only(clean):
                print(f"   ✅ Plain title search succeeded!")
                return normalize_lyrics_txt(clean)
            else:
                print(f"   ⚠️ Plain title result is non-Latin — not usable.")
    except Exception as e:
        print(f"   ⚠️ Plain title search failed: {e}")

    print(f"   ❌ All Genius search strategies exhausted.")
    return None


# ============================================================
# MAIN FETCH FUNCTION
# ============================================================

def _lrc_to_plain_text(lrc_text: str) -> str:
    """Strips LRC timestamps and returns clean plain-text lyrics."""
    lines = []
    for line in lrc_text.split('\n'):
        # Remove timestamp tokens like [01:23.45]
        cleaned = re.sub(r'\[\d{2}:\d{2}[.:]\d{2,3}\]', '', line).strip()
        if cleaned:
            lines.append(cleaned)
    return '\n'.join(lines)


def fetch_lyrics(title: str, artist: str, workspace_dir: str):
    """
    Tier 1 : syncedlyrics → valid .lrc, fully Latin → SYNCED ✅
    Tier 2 : .lrc has ANY non-Latin word OR no .lrc at all
             → fetch Genius (Romanized) plain text → PLAIN ✅
             → Genius not found → NONE → Telegram asks user

    Returns: (status, file_path)
      status: "SYNCED" | "PLAIN" | "NONE"
    """
    search_query = f"{title} {artist}"
    lrc_path = os.path.join(workspace_dir, "lyrics.lrc")
    txt_path = os.path.join(workspace_dir, "lyrics.txt")

    # ----------------------------------------------------------
    # TIER 1: Synced Lyrics
    # ----------------------------------------------------------
    print(f"\n[Tier 1] Searching for synced .lrc lyrics: '{search_query}'")
    try:
        lrc_text = syncedlyrics.search(search_query, save_path=lrc_path)

        if lrc_text and _is_valid_lrc(lrc_text):
            print(f"✅ Synced lyrics found!")

            if not _contains_non_latin_words(lrc_text):
                # Fully Latin — done ✅
                print(f"✅ Lyrics are fully Latin script. Using as-is.")
                # Also write a plain-text version so lyrics.txt is always present
                plain = _lrc_to_plain_text(lrc_text)
                with open(txt_path, 'w', encoding='utf-8') as f:
                    f.write(plain)
                print(f"✅ Plain-text copy saved to: {txt_path}")
                return "SYNCED", lrc_path

            # Non-Latin words detected — discard LRC, fall to Tier 2
            print(f"🌐 Non-Latin words detected. Discarding LRC, falling to Genius...")
            if os.path.exists(lrc_path):
                os.remove(lrc_path)
        else:
            print(f"⚠️ No valid timestamped LRC found.")
            if os.path.exists(lrc_path):
                os.remove(lrc_path)

    except Exception as e:
        print(f"⚠️ Synced fetch failed: {e}")

    # ----------------------------------------------------------
    # TIER 2: Genius Romanized Plain Text
    # ----------------------------------------------------------
    print(f"\n[Tier 2] Fetching Genius romanized plain text...")
    genius_text = _fetch_genius_romanized(title, artist)

    if genius_text:
        with open(txt_path, 'w', encoding='utf-8') as f:
            f.write(genius_text)
        print(f"✅ Normalized romanized lyrics saved to: {txt_path}")
        return "PLAIN", txt_path

    # ----------------------------------------------------------
    # TIER 3: Nothing worked — ask user
    # ----------------------------------------------------------
    print("❌ All automated fetches failed. Manual upload required.")
    return "NONE", None