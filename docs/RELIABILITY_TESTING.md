# Reliability verification

Install the checkout with `python -m pip install -e ".[studio,upload,test]"`. FFmpeg and FFprobe must be on PATH. Install the test browser with `python -m playwright install chromium`. Model-backed transcription is optional: `python -m pip install -r requirements-heavy.txt`; models and a suitable CPU/memory budget are required separately.

Build Studio in `apps/web-studio/frontend` with `npm ci`, `npm run check`, and `npm run build`. Build the legacy editor in `apps/webeditor_legacy/frontend` with `npm ci` and `npm run build`. Run these builds before browser regressions.

From the repository root, run:

```text
python -m ruff check src scripts tests --select F,E9
python -m pytest tests -q
python -m pip check
```

On Windows, if the default pytest temporary root is inaccessible, use a unique temporary directory:

```powershell
python -m pytest tests -q --basetemp "$env:TEMP\ef-tests-$([guid]::NewGuid().ToString('N'))"
```

Tests use temporary projects/databases, mocked chart/lyrics/ASR/upload providers, intercepted browser requests, and real FFmpeg for isolated media fixtures. They do not publish videos or use production projects. Two subprocess tests validate refresh serialization and OS lock recovery after termination.

`.github/workflows/reliability.yml` runs the checks on Windows and Linux with Python 3.10 and 3.13. A local successful run does not imply that a remote CI run succeeded.

## Operational decisions

- Weekly cycles begin Friday at midnight in `ECHOFORGE_TIMEZONE`, default `Asia/Kolkata`. A missed refresh catches up on the next run. An empty/failed chart does not complete the cycle. Changing the chart scope refreshes its snapshot even within a completed cycle.
- Automatic selection uses the latest successful chart snapshot. Historical songs and workflow statuses are retained; an explicit song-ID project request may still select a historical song. Existing databases retain their selection behavior until the first new successful snapshot.
- Automatic Whisper fallback creates review candidates. It cannot authorize a final timing promotion. Explicit timing approval must pass ordering, finite-value, duration and word-bound checks; semantic lyric correctness remains a human review responsibility.
- A timing publication writes a pending marker, both canonical artifacts, then a digest manifest. Interrupted/mismatched publications fail closed until synchronization or approval is retried. Legacy artifacts without a manifest are accepted for compatibility; corrupt JSON is an error.
- Known successful uploads are reused. A failed request with an uncertain remote outcome blocks retry until the existing remote video is reconciled through the explicit mark-uploaded command. Local tests cannot guarantee YouTube's remote behavior.
- Editors run on loopback with local origin checks. Studio supports static/fade templates. Playlist assignment is explicitly unsupported with the upload-only OAuth scope.

## Validation boundaries

Live chart extraction, lyric relevance, full ASR model accuracy, OAuth consent/refresh, Gemini and YouTube publication need a controlled integration acceptance pass. Automated checks validate local contracts and recovery, not arbitrary external-service responses or every visual font/platform combination. Optional Whisper dependencies are isolated from the standard installation so a Torch/model issue does not prevent the core application from starting.
