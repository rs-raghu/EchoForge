# EchoForge V3

Automated lyric-video pipeline controlled entirely through Telegram.
Scrape trending charts → review lyrics → watch a preview clip → publish to YouTube,
all without touching the server after initial setup.

---

## Quick Start

```bash
python run.py
```

That's it. One command starts everything — the pipeline engine and the Telegram bot —
in a single terminal with colour-coded, merged logs.

---

## First-Time Setup

### 1 — Install Python dependencies

```bash
pip install -r requirements.txt
```

### 2 — Install system dependencies

| Tool | macOS | Linux (Debian/Ubuntu) |
|---|---|---|
| **ffmpeg** | `brew install ffmpeg` | `apt install ffmpeg` |
| **Node.js 18+** | `brew install node` | `apt install nodejs npm` |

### 3 — Install Remotion inside the `remotion/` folder

```bash
cd remotion
npm install
cd ..
```

### 4 — Create your `.env` file

Create a file called `.env` in the project root and add:

```env
TELEGRAM_BOT_TOKEN=your_bot_token_from_BotFather
SECRET_PASSWORD=choose_any_password
YOUTUBE_PRIVACY=private
```

### 5 — Authorise YouTube uploads (one time only)

This opens a browser so you can log in to your Google account and grant upload
permission. Must be run interactively before the first upload.

```bash
python engine/workers/youtube_upload.py --auth-only
```

A `database/token.json` file is created. Future runs refresh it automatically.

### 6 — Run

```bash
python run.py
```

---

## Daily Workflow (100% in Telegram)

Once `run.py` is running, everything is controlled through the bot:

```
/start <password>
        │
        ▼
🎛️  Master Control Dashboard
        │
        ├─ "Run Chart Scraper"          ← fetches trending songs via ytmusicapi
        │         │
        │         ▼
        ├─ "Fetch Next from Queue"      ← stages the top unprocessed song
        │         │
        │         ▼
        │   Song Control Panel          ← live-updating every 3 seconds
        │         │
        └─ "Run Full (→ Publish)"       ← starts the full pipeline
                  │
                  ▼
        🎵  Audio downloaded automatically
                  │
                  ▼
        📝  Lyrics file sent to Telegram       ← read it, tap Approve / Edit / Reject
                  │
                  ▼  (if Approved)
        🧠  Demucs + Whisper sync runs         ← 10–40 min on CPU
                  │
                  ▼
        🎬  Remotion renders the video
                  │
                  ▼
        📱  60-second preview clip sent to Telegram  ← watch it, tap Upload or Discard
                  │
                  ▼  (if Upload)
        🚀  Video uploaded to YouTube automatically
```

You never need to open a file manager, SSH session, or browser during normal operation.

---

## .env Reference

| Variable | Required | Default | Description |
|---|---|---|---|
| `TELEGRAM_BOT_TOKEN` | ✅ | — | Token from [@BotFather](https://t.me/BotFather) |
| `SECRET_PASSWORD` | ✅ | — | Password required to open the dashboard via `/start` |
| `YOUTUBE_PRIVACY` | — | `private` | Upload privacy: `private` / `unlisted` / `public` |

> **Tip:** Keep `YOUTUBE_PRIVACY=private` while testing so nothing goes public by accident.

---

## Bot Commands

| Command | Description |
|---|---|
| `/start <password>` | Open the Master Control dashboard |
| `/cancel` | Cancel an in-progress lyrics-edit session |

---

## Dashboard Buttons

| Button | When visible | What it does |
|---|---|---|
| ▶️ Fetch Next from Queue | Dashboard | Stages the next DISCOVERED song |
| 🔍 Run Chart Scraper | Dashboard | Scrapes YouTube Music charts (cached 6 h) |
| 🔄 Refresh Dashboard | Dashboard | Reloads the job list |
| ⚙️ Open: Song Title | Dashboard | Opens the song's control panel |
| ▶️ Run Full (→ Publish) | Song panel — STAGED / PAUSED | Runs the full pipeline to YouTube |
| 🛠️ Assets Only | Song panel — STAGED / PAUSED | Stops after render, before upload |
| ✅ Approve Lyrics | Song panel — LYRICS_REVIEW_PENDING | Continues to AI sync |
| ✏️ Edit Natively | Song panel — LYRICS_REVIEW_PENDING | Send a corrected file or type new lyrics |
| 🚀 Upload to YouTube | Video preview message | Approves render and triggers upload |
| 🗑️ Discard | Song panel / video message | Marks the song as DISCARDED |
| 🛑 ABORT | Song panel — while running | Kills the worker process immediately |
| ⏸️ Pause at Checkpoint | Song panel — while running | Stops at the next phase boundary |
| 🔄 Retry | Song panel — FAILED | Re-runs from the failed phase |

---

## Pipeline State Machine

```
DISCOVERED
    │
    ▼
  STAGED  ──────────────────── user chooses target (Publish / Assets Only)
    │
    ▼  [fetch_audio worker]
AUDIO_FETCHED
    │
    ▼  [fetch_lyrics worker]
LYRICS_REVIEW_PENDING  ◄── lyrics file sent to Telegram
    │                       Approve / Edit / Reject
    ▼  [user approves]
LYRICS_APPROVED
    │
    ▼  [ai_sync worker: Demucs + Whisper]
ASSETS_READY
    │
    ▼  [render_video worker: Remotion]
PREVIEW_PENDING  ◄── 60-second preview clip sent to Telegram
    │                 Upload / Discard
    ▼  [user approves]
VIDEO_APPROVED
    │
    ▼  [youtube_upload worker]
PUBLISHED ✅


Side exits (reachable from any running phase)
─────────────────────────────────────────────
→  PAUSED      user taps Pause at Checkpoint
→  FAILED      worker process crashes
→  DISCARDED   user taps Discard
→  UNAVAILABLE video is geo/age-blocked or removed
```

---

## Project Structure

```
EchoForge V3/
│
├── run.py                      ← single launcher — start here
│
├── bot/
│   ├── __init__.py
│   └── main.py                 ← Telegram dashboard bot
│
├── engine/
│   ├── __init__.py
│   ├── orchestrator.py         ← pipeline daemon (polls DB every 2 s)
│   └── workers/
│       ├── __init__.py
│       ├── fetch_audio.py      ← yt-dlp audio download
│       ├── fetch_lyrics.py     ← syncedlyrics fetch
│       ├── ai_sync.py          ← Demucs + Whisper forced alignment
│       ├── render_video.py     ← Remotion render
│       └── youtube_upload.py   ← YouTube Data API v3 upload
│
├── discovery/
│   ├── __init__.py
│   └── chart_scraper.py        ← ytmusicapi chart scraper (no Selenium)
│
├── database/
│   ├── __init__.py
│   ├── db_manager.py           ← SQLite manager (WAL mode, thread-safe)
│   └── echoforge.db            ← auto-created on first run
│
├── utils/
│   ├── __init__.py
│   ├── config.py               ← paths and env var loader
│   └── logger.py               ← rotating file + console logging
│
├── remotion/                   ← Remotion video engine (Node.js)
│   ├── src/
│   │   ├── index.ts
│   │   ├── Root.tsx
│   │   └── LyricVideo.tsx
│   ├── package.json
│   └── remotion.config.ts
│
├── workspaces/                 ← auto-created, one folder per song
│   └── <video_id>/
│       ├── audio.mp3
│       ├── lyrics.lrc / lyrics.txt
│       ├── timestamps.json
│       ├── final_video.mp4
│       ├── final_video_preview.mp4
│       └── published_url.txt
│
├── logs/
│   └── echoforge.log           ← rotating log (5 MB × 5 files)
│
├── .env                        ← your secrets (never commit)
├── client_secrets.json         ← Google OAuth credentials (never commit)
└── requirements.txt
```

---

## How `run.py` Works

`run.py` spawns both services as child processes and merges their output into
one terminal with colour-coded prefixes:

```
[ORCH] ⚙️  Orchestrator Daemon started — watching DB for jobs...
[BOT ] 🤖 EchoForge Telegram Dashboard booting...
[BOT ] ✅ Bot online. Commands: /start <password>
[ORCH] ▶️  Fetching audio for "Espresso"...
[ORCH] ✅ Audio saved: workspaces/abc123/audio.mp3
```

**Auto-restart:** if either process crashes unexpectedly, `run.py` detects it
within 3 seconds and relaunches it automatically so your pipeline keeps running.

**Clean shutdown:** press Ctrl+C to stop both services gracefully.

---

## Testing Individual Workers

Every worker has its own CLI for isolated testing without running the full pipeline:

```bash
# Download audio only
python engine/workers/fetch_audio.py \
    --video-id dQw4w9WgXcQ \
    --workspace ./workspaces/test \
    --title "Never Gonna Give You Up"

# Fetch lyrics only
python engine/workers/fetch_lyrics.py \
    --title "Blinding Lights" \
    --artist "The Weeknd" \
    --workspace ./workspaces/test

# AI sync only (needs audio.mp3 + lyrics.txt in workspace)
python engine/workers/ai_sync.py \
    --workspace ./workspaces/test

# Render only (needs audio.mp3 + timestamps.json in workspace)
python engine/workers/render_video.py \
    --workspace ./workspaces/test \
    --title "Test Track" \
    --artist "Test Artist"

# Generate / refresh YouTube OAuth token (interactive, run once)
python engine/workers/youtube_upload.py --auth-only

# Scrape charts — prints results, does not write to DB
python discovery/chart_scraper.py --limit 10 --country US
```

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Bot says "Unauthorized" | Wrong password | Check `SECRET_PASSWORD` in `.env` |
| `database is locked` error | WAL mode not applied to old DB | Delete `database/echoforge.db` and restart |
| Lyrics fetch returns nothing | Song not on syncedlyrics | Upload a `.lrc` or `.txt` via Edit button |
| Demucs / Whisper takes 40+ min | Running on CPU | Expected — add `--device cuda` for GPU |
| Preview clip not sent to bot | ffmpeg not installed | `brew install ffmpeg` / `apt install ffmpeg` |
| Upload fails with 403 quota | Daily API limit hit | Wait 24 h — quota resets at midnight PT |
| Remotion render fails | Node / npm not set up | `cd remotion && npm install` |
| `[ORCH]` keeps restarting | Worker import error | Check that all `pip install` packages are present |
