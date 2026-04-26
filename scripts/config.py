"""
config.py

Central configuration for the EchoForge pipeline.
Every hardcoded path, model name, numeric threshold, and tuning constant
lives here.  All other modules import from this file — nothing is
duplicated or scattered across the codebase.

ENVIRONMENT OVERRIDES
─────────────────────
Some values can be overridden at runtime via .env without touching code:
  YOUTUBE_PRIVACY   = unlisted | public | private   (default: unlisted)
  WHISPER_MODEL     = any stable-whisper model name (default: large-v2)
  DEMUCS_MODEL      = any Demucs model name         (default: htdemucs)
  AUDIO_BITRATE     = MP3 bitrate in kbps           (default: 192)
"""

import os
from dotenv import load_dotenv

load_dotenv()

# Root of the Python source directory (same folder as this file).
# All other paths are resolved relative to this so the project can be
# moved without breaking anything.
_HERE = os.path.dirname(os.path.abspath(__file__))


# ─── Filesystem layout ────────────────────────────────────────────────────────

ASSETS_DIR       = os.path.normpath(os.path.join(_HERE, "..", "Assets"))
BACKGROUNDS_DIR  = os.path.join(ASSETS_DIR, "backgrounds")
LOGO_PATH        = os.path.join(ASSETS_DIR, "logo.png")

DB_DIR           = os.path.normpath(os.path.join(_HERE, "..", "Database"))
DB_PATH          = os.path.join(DB_DIR, "echoforge.db")

LOGS_DIR         = os.path.normpath(os.path.join(_HERE, "..", "Logs"))

VIDEO_ENGINE_DIR = os.path.normpath(os.path.join(_HERE, "..", "video-engine"))
REACT_PUBLIC_DIR = os.path.join(VIDEO_ENGINE_DIR, "public")

OUTPUT_DIR       = os.path.normpath(os.path.join(_HERE, "..", "Output"))


# ─── Audio download ───────────────────────────────────────────────────────────

AUDIO_FORMAT  = "bestaudio/best"
AUDIO_BITRATE = os.getenv("AUDIO_BITRATE", "192")   # MP3 output quality (kbps)


# ─── Vocal separation (Demucs) ────────────────────────────────────────────────

DEMUCS_MODEL = os.getenv("DEMUCS_MODEL", "htdemucs")


# ─── Forced alignment (Whisper) ───────────────────────────────────────────────

# 'large-v2' gives the best accuracy; use 'medium' or 'base' on low-RAM machines.
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "large-v2")


# ─── Video rendering ──────────────────────────────────────────────────────────

# Total intro duration before lyrics appear: 2 s logo + 3 s details screen.
INTRO_DURATION = 5.0

# How many background images cycle in Assets/backgrounds/ (modulo arithmetic).
NUM_BACKGROUNDS = 30

# ffmpeg seek position used when extracting the YouTube thumbnail frame.
# 4 s lands on the details screen (title + artist), which makes a clean thumbnail.
THUMBNAIL_TIMESTAMP = "00:00:04"


# ─── YouTube upload ───────────────────────────────────────────────────────────

# Privacy status for uploaded videos.  Set YOUTUBE_PRIVACY=public in .env
# when ready to go live.  Defaults to 'unlisted' so nothing is published
# by accident if the variable is missing or mistyped.
_VALID_PRIVACY  = {"public", "unlisted", "private"}
_privacy_raw    = os.getenv("YOUTUBE_PRIVACY", "unlisted").strip().lower()
YOUTUBE_PRIVACY = _privacy_raw if _privacy_raw in _VALID_PRIVACY else "unlisted"
if _privacy_raw not in _VALID_PRIVACY:
    import logging as _logging
    _logging.warning(
        "config: invalid YOUTUBE_PRIVACY value '%s' — defaulting to 'unlisted'. "
        "Valid values: %s", _privacy_raw, _VALID_PRIVACY
    )


# ─── Disk space thresholds ───────────────────────────────────────────────────
#
# Minimum free gigabytes required before each heavy phase starts.
# The pipeline aborts with a "LOW_DISK" signal if any threshold is not met,
# preventing cryptic mid-run failures from "no space left on device".
#
# Rationale for defaults:
#   AUDIO  : audio.mp3 ~50 MB + yt-dlp temp files + breathing room → 1.5 GB
#   DEMUCS : Demucs writes full vocal + accompaniment stems before renaming
#            (~200–500 MB per stem for a 4-minute track) → 3 GB
#   RENDER : Remotion output at 1080p/30fps for 3–5 min → 200–600 MB + Node
#            module cache + ffmpeg temp files → 2 GB
#
# Override via .env:
#   DISK_MIN_AUDIO_GB=2.0
#   DISK_MIN_DEMUCS_GB=5.0
#   DISK_MIN_RENDER_GB=3.0
DISK_MIN_AUDIO_GB  = float(os.getenv("DISK_MIN_AUDIO_GB",  "1.5"))
DISK_MIN_DEMUCS_GB = float(os.getenv("DISK_MIN_DEMUCS_GB", "3.0"))
DISK_MIN_RENDER_GB = float(os.getenv("DISK_MIN_RENDER_GB", "2.0"))


# ─── Lyrics line splitting ────────────────────────────────────────────────────

MAX_LINE_CHARS  = 58   # comfortable on-screen lyric line width
LYRICS_MIN_LEFT = 20   # never split within the first N characters of a line


# ─── Timestamp matching ───────────────────────────────────────────────────────

# Words that count as filler when deciding whether to merge short segments.
FILLER_SOUNDS = {
    "oh", "ah", "uh", "eh", "mm", "hmm", "hm", "na", "la", "da",
    "ooh", "aah", "ayy", "aye", "hey", "hah", "yeah", "yea", "ya",
    "woo", "whoa", "woah", "no", "oo", "du", "de", "huh",
}

# Segments with fewer than this many words are merged into their neighbours.
MIN_WORDS_STANDALONE = 3

# Dynamic LOOK_AHEAD formula:
#   window = BASE + (words_in_line × PER_WORD) + (misses_so_far × PER_MISS)
LOOK_AHEAD_BASE     = 6   # minimum scan window for any word
LOOK_AHEAD_PER_WORD = 1   # extra slots per word in the current line
LOOK_AHEAD_PER_MISS = 4   # extra slots per already-unmatched word (miss penalty)

# Commit guard: only advance the global word-pointer when this fraction of the
# line's words were matched.  Prevents a bad partial match from locking in a
# drifted pointer that mis-times every subsequent line.
MIN_MATCH_RATIO = 0.4

# Sanity-validation thresholds applied after matching.
MIN_SEGMENT_DURATION = 0.3    # seconds — segments shorter than this are extended
MIN_SEGMENT_GAP      = 0.05   # seconds — enforced gap between adjacent segments