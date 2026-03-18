import os
import re
import glob
import json
import shutil
import subprocess
import stable_whisper
from config import (
    DEMUCS_MODEL, AUDIO_BITRATE,
    WHISPER_MODEL,
    LOOK_AHEAD_BASE, LOOK_AHEAD_PER_WORD, LOOK_AHEAD_PER_MISS, MIN_MATCH_RATIO,
)

# ============================================================
# STEP 1: VOCAL ISOLATION
# ============================================================

def isolate_vocals(audio_path: str, workspace_dir: str) -> str | None:
    """
    Uses Demucs to separate the vocal stem from the full mix.
    Saves the result as vocals.mp3 directly in the workspace folder.
    Returns the path to vocals.mp3 or None on failure.
    """
    vocals_path = os.path.join(workspace_dir, "vocals.mp3")

    if os.path.exists(vocals_path):
        print(f"⏭️ vocals.mp3 already exists. Skipping Demucs.")
        return vocals_path

    print(f"🎙️ Starting Demucs vocal isolation...")
    print(f"   Input : {audio_path}")
    print(f"   ⏳ This will take a few minutes on CPU — hang tight...")

    try:
        result = subprocess.run(
            [
                "python", "-m", "demucs",
                "--two-stems", "vocals",
                "--mp3",
                "--mp3-bitrate", AUDIO_BITRATE,
                f"-n", DEMUCS_MODEL,
                "-o", workspace_dir,
                audio_path
            ],
            capture_output=True,
            text=True
        )

        if result.returncode != 0:
            print(f"❌ Demucs failed:\n{result.stderr}")
            return None

        pattern = os.path.join(workspace_dir, DEMUCS_MODEL, "**", "vocals.mp3")
        matches = glob.glob(pattern, recursive=True)

        if not matches:
            print(f"❌ Demucs ran but vocals.mp3 not found.")
            return None

        os.rename(matches[0], vocals_path)
        shutil.rmtree(os.path.join(workspace_dir, DEMUCS_MODEL), ignore_errors=True)

        print(f"✅ Vocal stem saved to: {vocals_path}")
        return vocals_path

    except Exception as e:
        print(f"❌ Demucs isolation crashed: {e}")
        return None


# ============================================================
# WORD-SEQUENCE HELPERS
# ============================================================

def _norm(s: str) -> str:
    """Normalize a word for fuzzy comparison: lowercase, strip non-alphanumeric."""
    return re.sub(r'[^\w]', '', s.lower())


def _seconds_to_lrc_ts(seconds: float) -> str:
    """Convert float seconds to LRC timestamp [mm:ss.cs]."""
    seconds = max(0.0, seconds)
    minutes = int(seconds // 60)
    secs    = int(seconds % 60)
    centis  = int(round((seconds - int(seconds)) * 100))
    return f"[{minutes:02d}:{secs:02d}.{centis:02d}]"


def _extract_words_from_result(result) -> list:
    """
    Flatten stable-whisper result into a word list:
      [{"word": str, "start": float, "end": float}, ...]
    """
    words = []
    for seg in result.segments:
        for w in seg.words:
            word  = w.word.strip() if w.word else ""
            start = w.start
            end   = w.end
            if word and start is not None and end is not None:
                words.append({"word": word, "start": start, "end": end})
    return words


def _sequence_match_lines(lyric_lines: list, all_words: list) -> list:
    """
    Maps Whisper word timestamps to lyric lines using greedy sequence matching.

    For each lyric line:
      1. Tokenize the line into expected words.
      2. Starting from the current whisper-word pointer, scan forward to match
         each expected word (allowing a small look-ahead for misheard words).
      3. The segment start = first matched word's start time.
         The segment end   = last matched word's end time.
      4. If no words matched, estimate timing from the previous segment.

    This is far more reliable than time-window matching because it respects
    the natural left-to-right order of lyrics.

    Args:
        lyric_lines: [{"text": str}, ...]  — from lyrics.txt (the truth)
        all_words  : [{"word": str, "start": float, "end": float}, ...]

    Returns:
        [{"text": str, "start": float, "end": float}, ...]
    """
    # Dynamic LOOK_AHEAD — imported from config.py

    wi = 0   # Current position in all_words
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
        misses   = 0   # words Whisper failed to match in this line

        for exp_w in expected:
            exp_norm = _norm(exp_w)

            # Dynamic window: wider for longer lines and grows with each miss.
            window = LOOK_AHEAD_BASE + len(expected) * LOOK_AHEAD_PER_WORD + misses * LOOK_AHEAD_PER_MISS
            limit  = min(temp_wi + window, len(all_words))

            found = False
            for k in range(temp_wi, limit):
                if _norm(all_words[k]["word"]) == exp_norm:
                    matched.append(all_words[k])
                    temp_wi = k + 1
                    found   = True
                    break

            if not found:
                misses += 1   # widen window for the next word

        # Commit guard: only advance the global pointer when enough words
        # matched.  A sparse match means the pointer likely drifted — fall
        # back to estimation and retry from the same wi position next line.
        match_ratio = len(matched) / len(expected) if expected else 0.0

        if matched and match_ratio >= MIN_MATCH_RATIO:
            wi        = temp_wi
            seg_start = matched[0]["start"]
            seg_end   = matched[-1]["end"]
        else:
            if matched and match_ratio < MIN_MATCH_RATIO:
                print(
                    f"  \u26a0\ufe0f  Low match ratio ({match_ratio:.0%}) for "
                    f"\"{line_text[:40]}\" — using time estimate."
                )
            # Fallback: estimate based on previous segment
            seg_start = segments[-1]["end"] if segments else 0.0
            seg_end   = seg_start + max(0.5, len(expected) * 0.35)

        segments.append({
            "text":  line_text,
            "start": round(seg_start, 3),
            "end":   round(seg_end,   3),
        })

    return segments


def _build_lrc_and_timestamps(
    lyrics_path:   str,
    all_words:     list,
    lrc_path:      str,
    json_path:     str,
) -> list:
    """
    Core function: reads lyrics.txt, sequence-matches Whisper words to each line,
    writes lyrics.lrc AND timestamps.json.

    Returns the list of segment dicts.
    """
    # Read clean lyric lines from lyrics.txt
    with open(lyrics_path, 'r', encoding='utf-8') as f:
        raw = f.read()

    lyric_lines = [
        {"text": l.strip()}
        for l in raw.split('\n')
        if l.strip()
    ]

    if not lyric_lines:
        print("❌ lyrics.txt is empty — nothing to match.")
        return []

    print(f"   📝 {len(lyric_lines)} lyric lines loaded from lyrics.txt")
    print(f"   🔤 {len(all_words)} word timestamps from Whisper")

    # Sequence match
    segments = _sequence_match_lines(lyric_lines, all_words)

    # ── Write lyrics.lrc ──────────────────────────────────────────────────────
    lrc_lines = [f"{_seconds_to_lrc_ts(seg['start'])} {seg['text']}" for seg in segments]
    with open(lrc_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lrc_lines))
    print(f"✅ LRC written: {len(lrc_lines)} lines → {lrc_path}")

    # ── Write timestamps.json ─────────────────────────────────────────────────
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump({"segments": segments}, f, indent=2, ensure_ascii=False)
    print(f"✅ timestamps.json written: {len(segments)} segments → {json_path}")

    return segments


# ============================================================
# STEP 2: FORCED ALIGNMENT + LRC / TIMESTAMPS GENERATION
# ============================================================

def align_lyrics(vocals_path: str, lyrics_path: str, workspace_dir: str) -> str | None:
    """
    Uses stable-whisper forced alignment to map each lyric LINE to its exact
    timestamp.

    PIPELINE:
      1. Load Whisper model.
      2. Run model.align() — gives us word-level timestamps.
      3. Save raw word-level JSON as timestamps_raw.json (backup).
      4. Sequence-match Whisper words back to the original lyrics.txt lines
         (NOT Whisper's own segment boundaries — those can be wrong).
      5. Write:
           lyrics.lrc       — one line per lyric line, proper timestamps
           timestamps.json  — {"segments": [{text, start, end}, ...]}

    IMPORTANT: We deliberately do NOT call merge_all_segments() or
    merge_by_punctuation() because they collapse everything into a single
    blob, destroying all line boundaries.
    """
    lrc_path      = os.path.join(workspace_dir, "lyrics.lrc")
    raw_json_path = os.path.join(workspace_dir, "timestamps_raw.json")
    json_path     = os.path.join(workspace_dir, "timestamps.json")

    print(f"\n🧠 Loading Whisper model for forced alignment...")
    print(f"   Vocals : {vocals_path}")
    print(f"   Lyrics : {lyrics_path}")

    try:
        with open(lyrics_path, 'r', encoding='utf-8') as f:
            target_text = f.read()

        if not target_text.strip():
            print("❌ lyrics.txt is empty — nothing to align.")
            return None

        model = stable_whisper.load_model(WHISPER_MODEL)

        print(f"⏱️ Aligning lyrics to vocals... (CPU mode — be patient)")
        # Run forced alignment — returns word-level timestamps per segment
        result = model.align(vocals_path, target_text, language='en')

        # ── Save raw word-level JSON as backup ────────────────────────────────
        result.save_as_json(raw_json_path)
        print(f"💾 Raw word-level data saved to: {raw_json_path}")

        # ── Extract flat word list ────────────────────────────────────────────
        all_words = _extract_words_from_result(result)
        if not all_words:
            print("⚠️ Whisper returned no word-level timestamps. Alignment may be poor.")

        # ── Build LRC + timestamps.json using lyrics.txt as line authority ────
        segments = _build_lrc_and_timestamps(
            lyrics_path = lyrics_path,
            all_words   = all_words,
            lrc_path    = lrc_path,
            json_path   = json_path,
        )

        if not segments:
            print("❌ No segments produced. Check lyrics.txt content.")
            return None

        # Preview
        print("\n── Alignment Preview (first 8 lines) ───────────────────────")
        for seg in segments[:8]:
            print(f"  [{seg['start']:.2f}s → {seg['end']:.2f}s]  {seg['text']}")
        print("────────────────────────────────────────────────────────────\n")

        print(f"✅ Alignment complete! LRC → {lrc_path}")
        print(f"✅ Timestamps  ready! JSON → {json_path}")
        return lrc_path

    except Exception as e:
        print(f"❌ Whisper alignment crashed: {e}")
        return None


# ============================================================
# MAIN ENTRY POINT
# ============================================================

def sync_lyrics(audio_path: str, lyrics_path: str, workspace_dir: str) -> str | None:
    """
    Full pipeline:
      1. Demucs  → isolate vocals → vocals.mp3
      2. Whisper → force-align lyrics.txt to vocals → lyrics.lrc + timestamps.json
    """
    print("\n🎚️ SYNC ENGINE STARTING...")

    vocals_path = isolate_vocals(audio_path, workspace_dir)
    if not vocals_path:
        print("❌ Sync Engine aborted: vocal isolation failed.")
        return None

    lrc_path = align_lyrics(vocals_path, lyrics_path, workspace_dir)
    if not lrc_path:
        print("❌ Sync Engine aborted: forced alignment failed.")
        return None

    print(f"\n✅ SYNC ENGINE COMPLETE → {lrc_path}")
    return lrc_path