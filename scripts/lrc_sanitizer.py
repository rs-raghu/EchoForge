import re
import os

def sanitize_lrc(lrc_path: str) -> bool:
    """
    Cleans up a malformed .lrc file where multiple lyric lines share a single
    timestamp, or where timestamps and text are mixed into a single blob.

    Strategy:
      1. Read the raw file.
      2. Use regex to split on every [mm:ss.xx] or [mm:ss:xx] timestamp token.
      3. Each token becomes its own line's timestamp.
      4. Multi-line text under a single timestamp gets split into sub-lines,
         each inheriting an interpolated timestamp so the file stays valid.
      5. Overwrites the original file with the clean version.

    Returns True on success, False on failure.
    """
    print(f"🧹 LRC Sanitizer running on: {lrc_path}")

    if not os.path.exists(lrc_path):
        print("❌ File not found.")
        return False

    with open(lrc_path, 'r', encoding='utf-8') as f:
        raw = f.read()

    if not raw.strip():
        print("❌ File is empty.")
        return False

    # --- STEP 1: Find all timestamp + text pairs ---
    # Matches both [mm:ss.xx] and [mm:ss:xx] formats
    pattern = re.compile(r'\[(\d{2}:\d{2}[.:]\d{2})\](.*?)(?=\[|\Z)', re.DOTALL)
    matches = pattern.findall(raw)

    if not matches:
        print("⚠️  No valid LRC timestamps found. File may already be plain text.")
        return False

    # --- STEP 2: Normalize timestamps to [mm:ss.xx] format ---
    def normalize_ts(ts: str) -> str:
        """Converts mm:ss:xx → mm:ss.xx if needed."""
        parts = ts.split(':')
        if len(parts) == 3:
            return f"{parts[0]}:{parts[1]}.{parts[2]}"
        return ts

    def ts_to_seconds(ts: str) -> float:
        """Converts mm:ss.xx to a float number of seconds."""
        ts = normalize_ts(ts)
        minutes, rest = ts.split(':')
        seconds, centiseconds = rest.split('.')
        return int(minutes) * 60 + int(seconds) + int(centiseconds) / 100

    def seconds_to_ts(total: float) -> str:
        """Converts float seconds back to mm:ss.xx string."""
        total = max(0.0, total)
        minutes = int(total // 60)
        seconds = int(total % 60)
        centiseconds = int(round((total - int(total)) * 100))
        return f"{minutes:02}:{seconds:02}.{centiseconds:02}"

    # --- STEP 3: Expand multi-line blocks ---
    clean_lines = []

    for i, (raw_ts, raw_text) in enumerate(matches):
        ts = normalize_ts(raw_ts)
        start_sec = ts_to_seconds(ts)

        # Figure out where this segment ends (start of next segment)
        if i + 1 < len(matches):
            next_ts = normalize_ts(matches[i + 1][0])
            end_sec = ts_to_seconds(next_ts)
        else:
            # Last segment — give it a 5 second window
            end_sec = start_sec + 5.0

        # Split the text block into individual non-empty lines
        sub_lines = [l.strip() for l in raw_text.strip().splitlines() if l.strip()]

        if not sub_lines:
            # Empty segment — keep a blank line as a pause marker
            clean_lines.append(f"[{ts}] ")
            continue

        if len(sub_lines) == 1:
            # Perfect — one timestamp, one line
            clean_lines.append(f"[{ts}] {sub_lines[0]}")
        else:
            # Multiple lines under one timestamp — interpolate evenly
            segment_duration = end_sec - start_sec
            step = segment_duration / len(sub_lines)

            for j, line in enumerate(sub_lines):
                interpolated_sec = start_sec + (j * step)
                interpolated_ts = seconds_to_ts(interpolated_sec)
                clean_lines.append(f"[{interpolated_ts}] {line}")

    if not clean_lines:
        print("❌ Sanitizer produced no output. Leaving original file intact.")
        return False

    # --- STEP 4: Overwrite the file ---
    clean_output = "\n".join(clean_lines)

    with open(lrc_path, 'w', encoding='utf-8') as f:
        f.write(clean_output)

    print(f"✅ Sanitized! {len(clean_lines)} clean lines written back to: {lrc_path}")
    return True


def sanitize_lrc_string(raw_lrc: str) -> str:
    """
    Same logic as sanitize_lrc() but works on a raw string instead of a file.
    Useful for sanitizing before saving to disk.
    Returns the cleaned LRC string, or the original if parsing fails.
    """
    pattern = re.compile(r'\[(\d{2}:\d{2}[.:]\d{2})\](.*?)(?=\[|\Z)', re.DOTALL)
    matches = pattern.findall(raw_lrc)

    if not matches:
        return raw_lrc  # Can't parse — return as-is

    def normalize_ts(ts):
        parts = ts.split(':')
        return f"{parts[0]}:{parts[1]}.{parts[2]}" if len(parts) == 3 else ts

    def ts_to_seconds(ts):
        ts = normalize_ts(ts)
        m, rest = ts.split(':')
        s, cs = rest.split('.')
        return int(m) * 60 + int(s) + int(cs) / 100

    def seconds_to_ts(total):
        total = max(0.0, total)
        m = int(total // 60)
        s = int(total % 60)
        cs = int(round((total - int(total)) * 100))
        return f"{m:02}:{s:02}.{cs:02}"

    clean_lines = []

    for i, (raw_ts, raw_text) in enumerate(matches):
        ts = normalize_ts(raw_ts)
        start_sec = ts_to_seconds(ts)
        end_sec = ts_to_seconds(normalize_ts(matches[i + 1][0])) if i + 1 < len(matches) else start_sec + 5.0

        sub_lines = [l.strip() for l in raw_text.strip().splitlines() if l.strip()]

        if not sub_lines:
            clean_lines.append(f"[{ts}] ")
        elif len(sub_lines) == 1:
            clean_lines.append(f"[{ts}] {sub_lines[0]}")
        else:
            step = (end_sec - start_sec) / len(sub_lines)
            for j, line in enumerate(sub_lines):
                clean_lines.append(f"[{seconds_to_ts(start_sec + j * step)}] {line}")

    return "\n".join(clean_lines)


# ============================================================
# STANDALONE TEST
# ============================================================
if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        path = sys.argv[1]
        sanitize_lrc(path)
    else:
        # Quick inline test with the example blob from the user
        test_lrc = """[00:19.64] I was a ghost, I was alone Eo duwojin ap gilsoge ( Ah ) Given the throne, I didn't know how to believe ( Hah ) I was the queen that I'm meant to be ( Ah )
[00:35.00] I lived two lives, tried to play both sides But I couldn't find my own place (Oh, oh)
[00:45.00] We're goin' up, up, up It's our moment You know together we're glowing Gonna be, gonna be golden"""

        print("=== INPUT ===")
        print(test_lrc)
        print("\n=== OUTPUT ===")
        print(sanitize_lrc_string(test_lrc))