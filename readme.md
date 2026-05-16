# EchoForge V3

Automated lyric-video pipeline controlled through Telegram.

## How to run

EchoForge is two separate processes that communicate through the SQLite database.
Start **both** in separate terminals:

```bash
# Terminal 1 — Orchestrator daemon (pipeline engine)
python engine/orchestrator.py

# Terminal 2 — Telegram bot (dashboard UI)
python bot/main.py
```

## First-time setup

1. Copy `.env.example` to `.env` and fill in all values.
2. Install Python dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Install system dependencies:
   - **ffmpeg** — `brew install ffmpeg` / `apt install ffmpeg`
   - **Node.js 18+** and `npm install` inside `remotion/`
4. Authorise the YouTube uploader (opens a browser):
   ```bash
   python engine/workers/youtube_upload.py --auth-only
   ```

## .env variables

| Variable | Required | Description |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | ✅ | From @BotFather |
| `SECRET_PASSWORD` | ✅ | Password to gate `/start` access |
| `YOUTUBE_PRIVACY` | — | `private` \| `unlisted` \| `public` (default: `private`) |

## Bot commands

| Command | Description |
|---|---|
| `/start <password>` | Open the Master Control dashboard |
| `/cancel` | Cancel an active lyrics-edit session |

## State machine

```
DISCOVERED  →  STAGED
                 │
                 ▼
           AUDIO_FETCHED
                 │
                 ▼
      LYRICS_REVIEW_PENDING  ← human approval
                 │
                 ▼
          LYRICS_APPROVED
                 │
                 ▼
           ASSETS_READY
                 │
                 ▼
          PREVIEW_PENDING  ← human approval
                 │
                 ▼
          VIDEO_APPROVED
                 │
                 ▼
            PUBLISHED ✅
```

## Testing individual workers

Every worker script has a CLI for standalone testing:

```bash
python engine/workers/fetch_audio.py  --video-id dQw4w9WgXcQ --workspace ./workspaces/test
python engine/workers/fetch_lyrics.py --title "Blinding Lights" --artist "The Weeknd" --workspace ./workspaces/test
python engine/workers/ai_sync.py      --workspace ./workspaces/test
python engine/workers/render_video.py --workspace ./workspaces/test --title "Test" --artist "Artist"
python engine/workers/youtube_upload.py --auth-only
python discovery/chart_scraper.py     --limit 5
```
