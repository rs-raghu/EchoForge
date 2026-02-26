"""
timestamp_processor.py

Converts stable_whisper's raw word-level timestamps.json into clean
line-level segments that match the actual lyric lines from lyrics.txt.

ARCHITECTURE:
  Primary source of truth  → lyrics.txt  (what the lines should be)
  Secondary source         → lyrics.lrc  (fallback if no .txt exists)
  Word timestamps source   → timestamps_raw.json (raw Whisper output)
                             OR timestamps.json   (if raw backup exists)

STRATEGY:
  1. Load lyric lines from lyrics.txt (preferred) or lyrics.lrc.
  2. Extract word-level timestamps from the raw Whisper JSON.
  3. Sequence-match: walk through Whisper words left-to-right, matching
     each lyric line's words in order — far more robust than time-window.
  4. Merge any leftover filler-only / very-short lines into neighbors.
  5. Overwrite timestamps.json with clean line-level segments.
"""

import json
import os
import re


# ─────────────────────────────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────────────────────────────

FILLER_SOUNDS = {
    "oh", "ah", "uh", "eh", "mm", "hmm", "hm", "na", "la", "da",
    "ooh", "aah", "ayy", "aye", "hey", "hah", "yeah", "yea", "ya",
    "woo", "whoa", "woah", "no", "oo", "du", "de", "huh"
}
MIN_WORDS_STANDALONE = 3
LOOK_AHEAD           = 8   # Max words to skip when searching for a match


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _norm(s: str) -> str:
    """Normalize a word: lowercase, strip all non-alphanumeric characters."""
    return re.sub(r'[^\w]', '', s.lower())


# ─────────────────────────────────────────────────────────────────────────────
# STEP 1A — PARSE LYRICS.TXT (PRIMARY, PREFERRED)
# ─────────────────────────────────────────────────────────────────────────────

def parse_lyrics_txt(txt_path: str) -> list:
    """
    Reads lyrics.txt and returns a list of lyric line dicts:
      [{"text": "lyric line"}, ...]

    Rules:
      - Blank lines (section separators) are skipped.
      - Each non-blank line becomes exactly one lyric line.
      - Preserves the natural line breaks that the lyrics writer intended.
    """
    with open(txt_path, 'r', encoding='utf-8') as f:
        raw = f.read()

    lines = [l.strip() for l in raw.split('\n') if l.strip()]
    print(f"  Parsed {len(lines)} lyric lines from lyrics.txt")
    return [{"text": l} for l in lines]


# ─────────────────────────────────────────────────────────────────────────────
# STEP 1B — PARSE LYRICS.LRC (FALLBACK)
# ─────────────────────────────────────────────────────────────────────────────

def parse_lrc_file(lrc_path: str) -> list:
    """
    Reads lyrics.lrc and returns lyric line dicts WITH timestamps:
      [{"timestamp": float_seconds, "text": "lyric line"}, ...]

    Used only when lyrics.txt is absent (e.g., the song came in via a
    pre-synced .lrc from syncedlyrics rather than through Whisper alignment).
    """
    with open(lrc_path, 'r', encoding='utf-8') as f:
        raw = f.read()

    ts_re = re.compile(r'\[(\d{2}):(\d{2})[.:](\d{2})\](.*?)(?=\[\d{2}:\d{2}[.:]\d{2}\]|\Z)', re.DOTALL)
    matches = ts_re.findall(raw)

    if not matches:
        print("WARNING: No LRC timestamps found.")
        return []

    def to_sec(mm, ss, cs):
        return int(mm) * 60 + int(ss) + int(cs) / 100

    lines = []
    for mm, ss, cs, text in matches:
        for sub in text.split('\n'):
            sub = sub.strip()
            if sub:
                lines.append({
                    "timestamp": to_sec(mm, ss, cs),
                    "text":      sub,
                })

    print(f"  Parsed {len(lines)} lyric lines from lyrics.lrc (fallback)")
    return lines


# ─────────────────────────────────────────────────────────────────────────────
# STEP 2 — EXTRACT ALL WORDS FROM WHISPER JSON
# ─────────────────────────────────────────────────────────────────────────────

def extract_all_words(data: dict) -> list:
    """
    Flattens stable_whisper's nested JSON into a flat word list.
    Structure: data.segments[].words[].{word, start, end}
    """
    words = []
    for seg in data.get("segments", []):
        for w in seg.get("words", []):
            word  = w.get("word", "").strip()
            start = w.get("start")
            end   = w.get("end")
            if word and start is not None and end is not None:
                words.append({"word": word, "start": start, "end": end})
    return words


# ─────────────────────────────────────────────────────────────────────────────
# STEP 3A — SEQUENCE-BASED WORD→LINE MATCHING (PRIMARY)
# ─────────────────────────────────────────────────────────────────────────────

def build_segments_from_txt(lyric_lines: list, all_words: list) -> list:
    """
    Maps Whisper word timestamps to lyric lines via greedy sequence matching.

    Why sequence matching instead of time-window matching?
      Time-window matching breaks badly when Whisper's segment boundaries
      don't align with the lyric lines (very common with K-pop, ad-libs,
      romanized text, or any non-standard pronunciation).

    Algorithm:
      - Maintain a global pointer `wi` into all_words.
      - For each lyric line, tokenize its words.
      - Scan forward from `wi`, allowing up to LOOK_AHEAD skips, to find
        each token in the Whisper word list.
      - seg.start = first matched word's start time.
        seg.end   = last matched word's end time.
      - Unmatched lines get estimated timing from their neighbors.

    Args:
        lyric_lines : [{"text": str}, ...]
        all_words   : [{"word": str, "start": float, "end": float}, ...]

    Returns:
        [{"text": str, "start": float, "end": float}, ...]
    """
    wi = 0
    segments = []

    for line in lyric_lines:
        line_text = line["text"]
        expected  = [w for w in line_text.split() if _norm(w)]

        if not expected:
            last_end = segments[-1]["end"] if segments else 0.0
            segments.append({"text": line_text, "start": last_end, "end": last_end + 0.5})
            continue

        matched  = []
        temp_wi  = wi

        for exp_w in expected:
            exp_norm = _norm(exp_w)
            limit    = min(temp_wi + LOOK_AHEAD, len(all_words))
            for k in range(temp_wi, limit):
                if _norm(all_words[k]["word"]) == exp_norm:
                    matched.append(all_words[k])
                    temp_wi = k + 1
                    break
            # If no match: Whisper mis-heard or skipped — continue anyway

        if matched:
            wi        = temp_wi
            seg_start = matched[0]["start"]
            seg_end   = matched[-1]["end"]
        else:
            # Fallback: estimate from previous segment
            seg_start = segments[-1]["end"] if segments else 0.0
            seg_end   = seg_start + max(0.5, len(expected) * 0.35)

        segments.append({
            "text":  line_text,
            "start": round(seg_start, 3),
            "end":   round(seg_end,   3),
        })

    return segments


# ─────────────────────────────────────────────────────────────────────────────
# STEP 3B — LRC-TIMESTAMP FALLBACK (when no word-level data available)
# ─────────────────────────────────────────────────────────────────────────────

def build_segments_from_lrc(lrc_lines: list) -> list:
    """
    Converts LRC timestamp lines directly to segments (no word matching).
    Used when:
      - The song came via syncedlyrics (pre-synced, no Whisper word JSON), OR
      - Whisper returned zero word timestamps.

    Each segment's end = the next segment's start.
    """
    segments = []
    n = len(lrc_lines)

    for i, line in enumerate(lrc_lines):
        start = line["timestamp"]
        end   = lrc_lines[i + 1]["timestamp"] if i + 1 < n else start + 5.0
        segments.append({
            "text":  line["text"],
            "start": round(start, 3),
            "end":   round(max(start + 0.1, end - 0.05), 3),
        })

    return segments


# ─────────────────────────────────────────────────────────────────────────────
# STEP 4 — MERGE FILLER / SHORT LINES
# ─────────────────────────────────────────────────────────────────────────────

def is_filler(text: str) -> bool:
    cleaned  = re.sub(r'[^\w\s]', '', text).lower()
    words    = [w for w in cleaned.split() if w]
    if not words:
        return True
    filler_count = sum(1 for w in words if w in FILLER_SOUNDS)
    return (filler_count / len(words)) >= 0.8


def merge_filler_segments(segments: list) -> list:
    """
    Merges filler-only or very-short segments into their neighbors.
    Filler segments (e.g., a lone "oh" or "ah") are prepended to the NEXT
    segment so the video shows them before the substantive lyric appears.
    """
    merged = list(segments)
    i = 0
    while i < len(merged):
        seg           = merged[i]
        should_merge  = (
            is_filler(seg["text"]) or
            len(seg["text"].split()) < MIN_WORDS_STANDALONE
        )

        if should_merge and len(merged) > 1:
            if i + 1 < len(merged):
                nxt = merged[i + 1]
                merged[i + 1] = {
                    "text":  seg["text"] + " " + nxt["text"],
                    "start": seg["start"],
                    "end":   nxt["end"],
                }
                merged.pop(i)
            elif i > 0:
                prv = merged[i - 1]
                merged[i - 1] = {
                    "text":  prv["text"] + " " + seg["text"],
                    "start": prv["start"],
                    "end":   seg["end"],
                }
                merged.pop(i)
                i -= 1
        else:
            i += 1
    return merged


# ─────────────────────────────────────────────────────────────────────────────
# MAIN ENTRY POINT
# ─────────────────────────────────────────────────────────────────────────────

def process_timestamps(workspace_folder: str) -> str | None:
    """
    Converts raw Whisper word timestamps into clean line-level segments.

    Looks for files in this priority order:
      1. lyrics.txt + timestamps_raw.json → best accuracy (Whisper + txt lines)
      2. lyrics.txt + timestamps.json     → same, with raw JSON as backup
      3. lyrics.lrc + timestamps_raw.json → word matching against LRC lines
      4. lyrics.lrc only                  → LRC timestamps used directly

    Always writes the result back to timestamps.json.
    """
    txt_path     = os.path.join(workspace_folder, "lyrics.txt")
    lrc_path     = os.path.join(workspace_folder, "lyrics.lrc")
    raw_json     = os.path.join(workspace_folder, "timestamps_raw.json")
    ts_json      = os.path.join(workspace_folder, "timestamps.json")

    # ── Determine which JSON to use for word-level data ───────────────────────
    word_json_path = None
    if os.path.exists(raw_json):
        word_json_path = raw_json
        print(f"Using word-level data from: timestamps_raw.json")
    elif os.path.exists(ts_json):
        word_json_path = ts_json
        print(f"Using word-level data from: timestamps.json")

    # ── Load word-level data ──────────────────────────────────────────────────
    all_words = []
    if word_json_path:
        with open(word_json_path, 'r', encoding='utf-8') as f:
            raw_data = json.load(f)
        all_words = extract_all_words(raw_data)
        print(f"  Extracted {len(all_words)} word timestamps from Whisper JSON.")
    else:
        print("  No Whisper JSON found — will use LRC timestamps directly.")

    # ── Choose line source and build segments ─────────────────────────────────
    segments = None

    if os.path.exists(txt_path) and all_words:
        # BEST PATH: lyrics.txt lines + Whisper word timestamps
        print("\nStrategy: lyrics.txt (line authority) + Whisper sequence matching")
        lyric_lines = parse_lyrics_txt(txt_path)
        if lyric_lines:
            segments = build_segments_from_txt(lyric_lines, all_words)

    if segments is None and os.path.exists(lrc_path) and all_words:
        # GOOD PATH: LRC lines + Whisper word timestamps
        print("\nStrategy: lyrics.lrc (line authority) + Whisper sequence matching")
        lrc_lines = parse_lrc_file(lrc_path)
        if lrc_lines:
            # Convert to the same dict format expected by build_segments_from_txt
            plain_lines = [{"text": l["text"]} for l in lrc_lines]
            segments = build_segments_from_txt(plain_lines, all_words)

    if segments is None and os.path.exists(lrc_path):
        # FALLBACK: LRC timestamps only (pre-synced .lrc from syncedlyrics)
        print("\nStrategy: lyrics.lrc timestamps only (no word-level data)")
        lrc_lines = parse_lrc_file(lrc_path)
        if lrc_lines:
            segments = build_segments_from_lrc(lrc_lines)

    if not segments:
        print("ERROR: Could not produce any segments. Check that lyrics.txt or lyrics.lrc exists.")
        return None

    # ── Merge filler segments ─────────────────────────────────────────────────
    before   = len(segments)
    segments = merge_filler_segments(segments)
    after    = len(segments)
    if before != after:
        print(f"  Merged {before - after} filler segment(s). Final count: {after}")

    # ── Backup original timestamps.json if it has not been backed up yet ──────
    if os.path.exists(ts_json) and not os.path.exists(raw_json):
        backup = ts_json.replace(".json", "_raw.json")
        import shutil
        shutil.copy(ts_json, backup)
        print(f"  Backed up original timestamps.json → timestamps_raw.json")

    # ── Write clean output ────────────────────────────────────────────────────
    with open(ts_json, 'w', encoding='utf-8') as f:
        json.dump({"segments": segments}, f, indent=2, ensure_ascii=False)
    print(f"\n✅ timestamps.json updated: {after} line-level segments → {ts_json}")

    # ── Preview ───────────────────────────────────────────────────────────────
    print("\n── Preview (first 8 segments) ──────────────────────────────────")
    for seg in segments[:8]:
        print(f"  [{seg['start']:.2f}s → {seg['end']:.2f}s]  {seg['text']}")
    print("────────────────────────────────────────────────────────────────\n")

    return ts_json


# ─────────────────────────────────────────────────────────────────────────────
# STANDALONE
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import glob
    import sys

    if len(sys.argv) > 1:
        workspace = sys.argv[1]
    else:
        folders = glob.glob(os.path.join("Assets", "*"))
        if not folders:
            print("No folders in Assets/")
            sys.exit(1)
        workspace = max(folders, key=os.path.getmtime)
        print(f"Using most recent workspace: {workspace}")

    process_timestamps(workspace)