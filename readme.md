# EchoForge Web Studio

EchoForge Web Studio is a local browser-based lyric-video production system.

The repository is organized by responsibility:

```text
apps/
  web-studio/
    frontend/          React browser app and built static assets

echoforge/
  database/            SQLite access layer
  discovery/           YouTube chart discovery
  engine/              Pipeline orchestrator and workers
  utils/               Shared config, logging, editing helpers
  web/                 Web Studio API, service layer, local server

renderer/
  remotion/            Remotion lyric-video renderer

scripts/               Build and maintenance scripts
database/              Local runtime database and OAuth token files
workspaces/            Local project media, lyrics, timestamps, renders
logs/                  Runtime logs
```

## Run

Build the browser app:

```bash
npm run web:build
```

Start the local studio:

```bash
python run.py --port 8765
```

Open:

```text
http://127.0.0.1:8765
```

## Worker Runner

The Web Studio updates the existing SQLite state machine. To process long-running jobs, run the orchestrator in another terminal:

```bash
python -m echoforge.engine.orchestrator
```

## Useful Commands

```bash
npm run web:build
npm run web:watch
python run.py --port 8765
python run.py --fastapi --port 8000
python -m echoforge.engine.orchestrator
```

## Runtime Notes

- Default binding is localhost only.
- Keep `.env`, `client_secrets.json`, `database/token.json`, local logs, and workspace media private.
- Discovery depends on Playwright and BeautifulSoup.
- Rendering depends on Node.js, Remotion, and FFmpeg.
