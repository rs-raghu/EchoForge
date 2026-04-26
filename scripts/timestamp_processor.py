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
from config import (


    FILLER_SOUNDS, MIN_WORDS_STANDALONE,
    LOOK_AHEAD_BASE, LOOK_AHEAD_PER_WORD, LOOK_AHEAD_PER_MISS, MIN_MATCH_RATIO,
    MIN_SEGMENT_DURATION, MIN_SEGMENT_GAP,
)

from logger import get_logger
log = get_logger(__name__)



# ─────────────────────────────────────────────────────────────────────────────
# CONFIG — all constants imported from config.py
# ─────────────────────────────────────────────────────────────────────────────


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _norm(s: str) -> str:
    """Normalize a word: lowercase, strip all non-alphanumeric characters."""
    return re.sub(r'[^\w]', '', s.lower())
def _fill_word_timestamps(
    expected_words: list,
    word_ts: list,
    seg_start: float,
    seg_end: float,
) -> list:
    """
    Returns a complete word-timestamp list the same length as expected_words.

    word_ts is a parallel list:
      - Non-None entry: {"word": str, "start": float, "end": float}  (Whisper matched)
      - None entry    : word Whisper missed — timing will be interpolated

    Interpolation strategy:
      Between two matched anchors → distribute missing words linearly in the
        gap between left_anchor.end and right_anchor.start.
      Before the first anchor     → distribute from seg_start to anchor.start.
      After the last anchor       → distribute from anchor.end to seg_end.
      No anchors at all           → distribute all words evenly across the segment.
    """
    n = len(expected_words)
    result = list(word_ts)           # shallow copy

    anchors = [(i, wt) for i, wt in enumerate(result) if wt is not None]

    def _spread(words_slice, t_start, t_end):
        """Distribute word_slice evenly from t_start to t_end."""
        k = len(words_slice)
        if k == 0:
            return []
        step = (t_end - t_start) / k
        return [
            {
                "word":  words_slice[j],
                "start": round(t_start + j * step, 3),
                "end":   round(t_start + (j + 1) * step, 3),
            }
            for j in range(k)
        ]

    if not anchors:
        # No Whisper matches at all — spread evenly across the whole segment
        filled = _spread(expected_words, seg_start, seg_end)
        return filled

    # ── Before the first anchor ───────────────────────────────────────────────
    first_i, first_wt = anchors[0]
    if first_i > 0:
        pre = _spread(expected_words[:first_i], seg_start, first_wt["start"])
        for j, entry in enumerate(pre):
            result[j] = entry

    # ── Between consecutive anchors ───────────────────────────────────────────
    for k in range(len(anchors) - 1):
        left_i,  left_wt  = anchors[k]
        right_i, right_wt = anchors[k + 1]
        gap_indices = list(range(left_i + 1, right_i))
        if gap_indices:
            gap_words = [expected_words[gi] for gi in gap_indices]
            filled    = _spread(gap_words, left_wt["end"], right_wt["start"])
            for j, gi in enumerate(gap_indices):
                result[gi] = filled[j]

    # ── After the last anchor ─────────────────────────────────────────────────
    last_i, last_wt = anchors[-1]
    if last_i < n - 1:
        post_words = expected_words[last_i + 1:]
        post       = _spread(post_words, last_wt["end"], seg_end)
        for j, entry in enumerate(post):
            result[last_i + 1 + j] = entry

    return result


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
    log.info(f"  Parsed {len(lines)} lyric lines from lyrics.txt")
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
        log.info("WARNING: No LRC timestamps found.")
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

    log.info(f"  Parsed {len(lines)} lyric lines from lyrics.lrc (fallback)")
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
    Maps Whisper word timestamps to lyric lines via greedy sequence matching,
    and attaches per-word timing to each segment for karaoke highlighting.

    Algorithm:
      - Maintain a global pointer `wi` into all_words.
      - For each lyric line, tokenize its words.
      - Scan forward from `wi`, allowing a dynamic LOOK_AHEAD window, to match
        each expected word to a Whisper word.
      - Track which expected word index each match corresponds to so missed
        words can be interpolated later.
      - seg.start = first matched word's start time.
        seg.end   = last matched word's end time.
      - _fill_word_timestamps() interpolates timing for any missed words.
      - Unmatched lines (ratio < MIN_MATCH_RATIO) fall back to time-estimation
        and get evenly-distributed word timings across the estimated window.

    Args:
        lyric_lines : [{"text": str}, ...]
        all_words   : [{"word": str, "start": float, "end": float}, ...]

    Returns:
        [{"text": str, "start": float, "end": float,
          "words": [{"word": str, "start": float, "end": float}]}, ...]
    """
    wi = 0
    segments = []

    for line in lyric_lines:
        line_text = line["text"]
        expected  = [w for w in line_text.split() if _norm(w)]

        if not expected:
            last_end = segments[-1]["end"] if segments else 0.0
            segments.append({
                "text":  line_text,
                "start": last_end,
                "end":   last_end + 0.5,
                "words": [],
            })
            continue

        # word_ts[i] = matched Whisper entry for expected[i], or None if missed
        word_ts  = [None] * len(expected)
        matched  = []   # all successfully matched entries (for seg timing)
        temp_wi  = wi
        misses   = 0

        for ei, exp_w in enumerate(expected):
            exp_norm = _norm(exp_w)

            window = LOOK_AHEAD_BASE + len(expected) * LOOK_AHEAD_PER_WORD + misses * LOOK_AHEAD_PER_MISS
            limit  = min(temp_wi + window, len(all_words))

            found = False
            for k in range(temp_wi, limit):
                if _norm(all_words[k]["word"]) == exp_norm:
                    entry = {
                        "word":  exp_w,                    # use lyrics.txt text
                        "start": all_words[k]["start"],
                        "end":   all_words[k]["end"],
                    }
                    word_ts[ei] = entry
                    matched.append(all_words[k])
                    temp_wi = k + 1
                    found   = True
                    break

            if not found:
                misses += 1

        match_ratio = len(matched) / len(expected) if expected else 0.0

        if matched and match_ratio >= MIN_MATCH_RATIO:
            wi        = temp_wi
            seg_start = matched[0]["start"]
            seg_end   = matched[-1]["end"]
        else:
            if matched and match_ratio < MIN_MATCH_RATIO:
                log.info(
                    f"  ⚠️  Low match ratio ({match_ratio:.0%}) for "
                    f'"{line_text[:40]}" — using time estimate, not advancing pointer.'
                )
            seg_start = segments[-1]["end"] if segments else 0.0
            seg_end   = seg_start + max(0.5, len(expected) * 0.35)

        seg_start = round(seg_start, 3)
        seg_end   = round(seg_end,   3)

        # Fill interpolated timing for any missed words
        words = _fill_word_timestamps(expected, word_ts, seg_start, seg_end)

        segments.append({
            "text":  line_text,
            "start": seg_start,
            "end":   seg_end,
            "words": words,
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
                    "words": (seg.get("words") or []) + (nxt.get("words") or []),
                }
                merged.pop(i)
            elif i > 0:
                prv = merged[i - 1]
                merged[i - 1] = {
                    "text":  prv["text"] + " " + seg["text"],
                    "start": prv["start"],
                    "end":   seg["end"],
                    "words": (prv.get("words") or []) + (seg.get("words") or []),
                }
                merged.pop(i)
                i -= 1
        else:
            i += 1
    return merged


# ─────────────────────────────────────────────────────────────────────────────
# STEP 5 — TIMESTAMP SANITY VALIDATION & AUTO-FIX
# ─────────────────────────────────────────────────────────────────────────────

# MIN_SEGMENT_DURATION and MIN_SEGMENT_GAP are imported from config.py


def validate_and_fix_segments(segments: list) -> list:
    """
    Audits every segment for four classes of bad timestamps produced by
    Whisper or the fallback estimators, and fixes each one in-place.

    Problems detected and corrected (in order):

    1. Negative start  — clamp start to 0.0.
       Cause: Whisper occasionally returns a word at t < 0.

    2. Backwards segment  — end <= start.
       Fix: set end = start + estimated_duration based on word count.
       Cause: Whisper word boundaries can cross when speech is very fast.

    3. Overlap with next segment  — seg[i].end > seg[i+1].start.
       Fix: clip seg[i].end = seg[i+1].start - MIN_SEGMENT_GAP.
       Cause: sequence matching sometimes assigns the same timestamp region
       to two consecutive lines.

    4. Zero / sub-minimum duration after all fixes  — end - start < MIN_SEGMENT_DURATION.
       Fix: extend end = start + MIN_SEGMENT_DURATION.
       Cause: can result from the overlap clip above on very tight segments.

    All fixes are logged with the line text so you can spot patterns.
    The list is modified in-place AND returned for convenience.
    """
    fixed_negative  = 0
    fixed_backwards = 0
    fixed_overlaps  = 0
    fixed_short     = 0

    for i, seg in enumerate(segments):
        label = f"  [{i}] \"{seg['text'][:40]}\""

        # ── Fix 1: negative start ─────────────────────────────────────────────
        if seg["start"] < 0.0:
            log.warning(f"⚠️  Negative start {seg['start']:.3f}s clamped to 0.0 {label}")
            seg["start"] = 0.0
            fixed_negative += 1

        # ── Fix 2: backwards segment (end <= start) ───────────────────────────
        if seg["end"] <= seg["start"]:
            word_count   = max(1, len(seg["text"].split()))
            estimated    = round(word_count * 0.4, 3)   # ~0.4 s per word
            new_end      = round(seg["start"] + estimated, 3)
            log.info(
                f"⚠️  Backwards segment [{seg['start']:.3f}s → {seg['end']:.3f}s] "
                f"fixed → end={new_end:.3f}s {label}"
            )
            seg["end"]  = new_end
            fixed_backwards += 1

        # ── Fix 3: overlap with the next segment ──────────────────────────────
        if i + 1 < len(segments):
            next_start = segments[i + 1]["start"]
            if seg["end"] > next_start - MIN_SEGMENT_GAP:
                clipped = round(next_start - MIN_SEGMENT_GAP, 3)
                if clipped > seg["start"]:   # only clip if it leaves some duration
                    log.info(
                        f"⚠️  Overlap: seg[{i}].end {seg['end']:.3f}s > "
                        f"seg[{i+1}].start {next_start:.3f}s — "
                        f"clipped to {clipped:.3f}s {label}"
                    )
                    seg["end"]     = clipped
                    fixed_overlaps += 1

        # ── Fix 4: sub-minimum duration (may result from Fix 3) ───────────────
        if seg["end"] - seg["start"] < MIN_SEGMENT_DURATION:
            # Don't extend past the next segment's start
            max_end = (
                round(segments[i + 1]["start"] - MIN_SEGMENT_GAP, 3)
                if i + 1 < len(segments)
                else seg["start"] + MIN_SEGMENT_DURATION
            )
            new_end = min(round(seg["start"] + MIN_SEGMENT_DURATION, 3), max_end)
            if new_end > seg["end"]:
                log.info(
                    f"⚠️  Short segment ({seg['end'] - seg['start']:.3f}s) "
                    f"extended to {new_end - seg['start']:.3f}s {label}"
                )
                seg["end"]  = new_end
                fixed_short += 1

    total = fixed_negative + fixed_backwards + fixed_overlaps + fixed_short
    if total == 0:
        log.info("✅ Timestamp validation passed — no issues found.")
    else:
        log.info(
            f"🔧 Timestamp validation fixed {total} issue(s): "
            f"{fixed_negative} negative, {fixed_backwards} backwards, "
            f"{fixed_overlaps} overlaps, {fixed_short} short."
        )

    return segments


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
        log.info(f"Using word-level data from: timestamps_raw.json")
    elif os.path.exists(ts_json):
        word_json_path = ts_json
        log.info(f"Using word-level data from: timestamps.json")

    # ── Load word-level data ──────────────────────────────────────────────────
    all_words = []
    if word_json_path:
        with open(word_json_path, 'r', encoding='utf-8') as f:
            raw_data = json.load(f)
        all_words = extract_all_words(raw_data)
        log.info(f"  Extracted {len(all_words)} word timestamps from Whisper JSON.")
    else:
        log.info("  No Whisper JSON found — will use LRC timestamps directly.")

    # ── Choose line source and build segments ─────────────────────────────────
    segments = None

    if os.path.exists(txt_path) and all_words:
        # BEST PATH: lyrics.txt lines + Whisper word timestamps
        log.info("\nStrategy: lyrics.txt (line authority) + Whisper sequence matching")
        lyric_lines = parse_lyrics_txt(txt_path)
        if lyric_lines:
            segments = build_segments_from_txt(lyric_lines, all_words)

    if segments is None and os.path.exists(lrc_path) and all_words:
        # GOOD PATH: LRC lines + Whisper word timestamps
        log.info("\nStrategy: lyrics.lrc (line authority) + Whisper sequence matching")
        lrc_lines = parse_lrc_file(lrc_path)
        if lrc_lines:
            # Convert to the same dict format expected by build_segments_from_txt
            plain_lines = [{"text": l["text"]} for l in lrc_lines]
            segments = build_segments_from_txt(plain_lines, all_words)

    if segments is None and os.path.exists(lrc_path):
        # FALLBACK: LRC timestamps only (pre-synced .lrc from syncedlyrics)
        log.info("\nStrategy: lyrics.lrc timestamps only (no word-level data)")
        lrc_lines = parse_lrc_file(lrc_path)
        if lrc_lines:
            segments = build_segments_from_lrc(lrc_lines)

    if not segments:
        log.info("ERROR: Could not produce any segments. Check that lyrics.txt or lyrics.lrc exists.")
        return None

    # ── Merge filler segments ─────────────────────────────────────────────────
    before   = len(segments)
    segments = merge_filler_segments(segments)
    after    = len(segments)
    if before != after:
        log.info(f"  Merged {before - after} filler segment(s). Final count: {after}")

    # ── Validate and fix timestamps ───────────────────────────────────────────
    # Runs after filler merging so we validate the final shape the renderer
    # will actually see — not intermediate segments that will be merged away.
    log.info("\n── Timestamp Validation ────────────────────────────────────────")
    segments = validate_and_fix_segments(segments)
    log.debug("────────────────────────────────────────────────────────────────")

    # ── Backup original timestamps.json if it has not been backed up yet ──────
    if os.path.exists(ts_json) and not os.path.exists(raw_json):
        backup = ts_json.replace(".json", "_raw.json")
        import shutil
        shutil.copy(ts_json, backup)
        log.info(f"  Backed up original timestamps.json → timestamps_raw.json")

    # ── Write clean output ────────────────────────────────────────────────────
    with open(ts_json, 'w', encoding='utf-8') as f:
        json.dump({"segments": segments}, f, indent=2, ensure_ascii=False)
    log.info(f"\n✅ timestamps.json updated: {after} line-level segments → {ts_json}")

    # ── Preview ───────────────────────────────────────────────────────────────
    log.info("\n── Preview (first 8 segments) ──────────────────────────────────")
    for seg in segments[:8]:
        log.debug(f"  [{seg['start']:.2f}s → {seg['end']:.2f}s]  {seg['text']}")
    log.debug("────────────────────────────────────────────────────────────────\n")

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