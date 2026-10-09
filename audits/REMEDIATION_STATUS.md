# Reliability remediation status

The audit reports retain the original baseline findings and line numbers. This register records the subsequent fixes.

## Git preservation

The audited existing code and both reports were pushed before implementation to `origin/codex/reliability-remediation` at `d748058`. Local and remote main have unrelated histories; neither was force-pushed or overwritten.

## High-priority changes

All High findings now have implemented corrections, with isolated regression coverage. The weekly policy is now a Friday-start cycle with catch-up after downtime. Chart refresh and project allocation use OS-owned locks. Invalid media, stale caches and rejected sync candidates cannot count as completed work. Rendering stages to a temporary output before atomic replacement. One durable job service handles CLI and editor requests, preserves approved metadata, and recovers interrupted owners. A shared fail-closed upload ledger prevents duplicate inserts and records ambiguous network outcomes for explicit reconciliation. Editor HTTP routes expose only public media, enforce local origin/path/resource boundaries and preserve state history. Studio now has an API and a `run.bat studio` launch command backed by the same pipeline.

The supported Studio template animations are static and fade. Unsupported animations are removed from the selector rather than silently rendered incorrectly. Playlist assignment returns an explicit unsupported-operation error because the existing upload-only OAuth scope cannot manage playlists. Studio `run_full` stops at the timing review checkpoint; it does not automatically authorize publication.

## Final verification

- 88 automated checks passed in both the host environment and a fresh Python 3.13 environment. Final strengthened renderer-entry and portable-launcher checks also passed in the isolated Low regression run.
- Real FFmpeg audio conversion, muted/silent audio output, command-line rendering and a complete Studio approval/design/final-render workflow tested in temporary projects.
- Chromium tests verify failed saves block rendering, approved metadata reaches the job endpoint, delayed saves preserve newer text, metadata controls unlock after repeated saves, first Shift-click/range selection works, and mute/solo settings survive save/reopen.
- Two independent Python processes refresh one weekly cycle once; a terminated worker releases its OS lock.
- Studio TypeScript checking passes; its frontend builds with the declared local dependencies (`npm ci`, no reported npm vulnerabilities).
- Both frontend builds and Studio TypeScript checks passed. The legacy build reports optional font fallback URLs missing at build time; its bundled TTF fallback remains available.
- A fresh editable installation of studio/upload/test extras succeeded; pip check reported no broken requirements and CLI startup/import smoke checks passed. The fresh test environment emitted one Starlette test-client deprecation warning.
- Live charts, lyric APIs, model downloads, OAuth, Gemini and YouTube publication have not been exercised. Production projects, secrets and databases are not test fixtures.
- Python 3.10 syntax is validated. Python 3.10 runtime, Linux runtime and remote CI results are not locally confirmed; the GitHub connector returned no commit-status records.

## Medium-priority changes

All Medium findings now have corrections or an explicit documented acceptance policy. Current chart membership is stored transactionally without removing history. Environment loading occurs before settings evaluation; credential aliases resolve consistently. Shared LRC parsing handles offsets, multiple tags and blank interval boundaries. Editors are keyed by project, serialize requests, preserve newer dirty revisions, and disable metadata/design edits while mutations are pending. Failed upload reports cannot imply success. Canonical JSON writes use atomic replacement, stage updates merge under a shared lock, complete sync operations serialize across workers, and paired timing publication has a completion manifest. Direct runtime dependencies and optional capabilities are declared in the package; regression checks have a CI workflow.

Validation: 18 new Medium regressions passed, delayed-save and repeat-metadata-save Chromium checks passed, legacy first Shift-click/range selection passed, both frontend builds passed, Studio TypeScript passed, Ruff F/E9 passed, Python 3.10 syntax parsing passed, and a fresh Python 3.13 install/import/pip-check/full-suite run passed. That fresh environment emitted one Starlette test-client deprecation warning; no functional failures occurred. CI execution and a Python 3.10 runtime run are still distinct verification steps.

See [testing instructions and operational policies](../docs/RELIABILITY_TESTING.md). The timing-quality and current-chart ambiguities are resolved conservatively in code and documented, without claiming external lyric/ASR correctness.

## Low-priority changes and final integration checks

The Windows launcher now resolves its own checkout. The renderer module defines helpers before its executable entry point. Legacy mute/solo controls modify persistent track state, affect preview and exported audio, and restore after reopening. Legacy JSON persistence now uses atomic replacement and reports corruption explicitly. Browser checks and real FFmpeg amplitude checks verify these behaviors.

Final integration review also validates project/style resource limits, forwards the approved thumbnail path through the uploader, rejects invalid thumbnail locations and made-for-kids types before insert, and gives the Google HTTP transport a 60-second socket timeout. Successful remote IDs remain durable before optional thumbnail handling.

## Verification discipline

The Medium checkpoint initially contained a missing import caught by the final static check. It was corrected immediately in b974f65, with a regression importing every source module. The final verification gate passes Ruff F/E9 across source, scripts, tests and the legacy backend before committing/pushing. The original audit documents remain unchanged as historical baseline evidence.

## Issue register

| ID | Severity | Audit title | Remediation status |
|---|---|---|---|
| LOGIC-001 | High | Weekly refresh has no missed-window recovery | Implemented; isolated regression validation |
| LOGIC-002 | High | Empty chart is recorded as successful refresh | Implemented; isolated regression validation |
| DATA-003 | Medium | Selection retains obsolete chart ranks | Implemented; regression checks and documented policy |
| DATA-004 | High | Unicode identities collide and silently drop songs | Implemented; isolated regression validation |
| STATE-005 | High | Song claims and project allocation are not exclusive | Implemented; isolated regression validation |
| CONFIG-006 | Medium | Environment loading and credential names disagree | Implemented; regression checks and documented policy |
| MEDIA-007 | High | Invalid audio can be accepted as normalized success | Implemented; isolated regression validation |
| MEDIA-008 | Medium | Force-normalize uses the same input and output | Implemented; regression checks and documented policy |
| STATE-009 | High | Artifact caches ignore validity and input changes | Implemented; isolated regression validation |
| SYNC-010 | High | Failed transfer overwrites approved final lyrics | Implemented; isolated regression validation |
| SYNC-011 | Medium | Invalid existing LRC prevents automatic fallback | Implemented; regression checks and documented policy |
| SYNC-012 | Medium | Lyric JSON and LRC parser contracts diverge | Implemented; regression checks and documented policy |
| RENDER-013 | High | Prepare then render omits declared background | Implemented; isolated regression validation |
| RENDER-014 | High | Export differs from approved visual/audio edits | Implemented; isolated regression validation |
| RENDER-015 | Medium | Missing clips produce invalid FFmpeg input indices | Implemented; regression checks and documented policy |
| RENDER-016 | High | FFmpeg stderr can deadlock long renders | Implemented; isolated regression validation |
| RENDER-017 | Low | Module entry executes before helper definitions | Implemented; browser/subprocess/media regression validation |
| STATE-018 | High | Running jobs permanently block after restart | Implemented; isolated regression validation |
| INTEGRATION-019 | High | Render modal discards approved metadata and schedule | Implemented; isolated regression validation |
| UPLOAD-020 | High | Primary upload bypasses duplicate protection | Implemented; isolated regression validation |
| STATE-021 | High | State writers destroy or contradict workflow history | Implemented; isolated regression validation |
| STATE-022 | Medium | Failed upload report is displayed as uploaded | Implemented; regression checks and documented policy |
| FLOW-023 | High | Workflow continues failures and chooses a previous project | Implemented; isolated regression validation |
| SEC-024 | High | Root media route exposes credential files | Implemented; isolated regression validation |
| SEC-025 | High | Untrusted paths and unbounded renders lack constraints | Implemented; isolated regression validation |
| INTEGRATION-026 | High | Studio has no compatible backend in repository | Implemented; isolated regression validation |
| UI-027 | Medium | Studio async responses can lose or misroute edits | Implemented; regression checks and documented policy |
| BUILD-028 | Medium | Declared Python minimum cannot parse metadata generator | Implemented; regression checks and documented policy |
| DB-029 | Medium | SQLite transaction contexts do not close connections | Implemented; regression checks and documented policy |
| LYRICS-030 | Medium | Search normalization removes x within words | Implemented; regression checks and documented policy |
| CHART-031 | Medium | Numeric titles are treated as metrics | Implemented; regression checks and documented policy |
| UPLOAD-032 | Medium | Privacy alias is ignored by default visibility | Implemented; regression checks and documented policy |
| TIME-033 | Medium | Refresh completion uses host calendar zone | Implemented; regression checks and documented policy |
| START-034 | Low | Launcher hardcodes obsolete checkout path | Implemented; browser/subprocess/media regression validation |
| UI-035 | Medium | First legacy Shift-click uses undeclared selection variable | Implemented; regression checks and documented policy |
| UI-036 | Low | Legacy mute/solo controls do not affect audio | Implemented; browser/subprocess/media regression validation |
| QA-037 | Medium | Automated regression test files are empty | Implemented; regression checks and documented policy |
| BUILD-038 | Medium | Package omits direct runtime dependency declaration | Implemented; regression checks and documented policy |
| STATE-039 | Medium | JSON state writes are not crash-safe | Implemented; regression checks and documented policy |
| SYNC-040 | Medium | Timing quality acceptance is underspecified | Implemented; regression checks and documented policy |
| TIME-041 | High | Past or timezone-naive publish times are forwarded unchecked | Implemented; isolated regression validation |


## Regression evidence by area

| Audit IDs | Primary regression coverage |
|---|---|
| LOGIC-001, LOGIC-002, TIME-033 | tests/test_reliability.py; tests/test_medium_regressions.py; tests/test_process_recovery.py |
| DATA-003, DATA-004, STATE-005, DB-029 | tests/test_reliability.py; tests/test_medium_regressions.py |
| CONFIG-006, BUILD-028, BUILD-038, QA-037 | tests/test_medium_regressions.py; fresh package installation/import/pip-check; CI configuration |
| MEDIA-007, MEDIA-008, STATE-009 | tests/test_reliability.py; tests/test_sync_cache.py |
| SYNC-010, SYNC-011, SYNC-012, SYNC-040 | tests/test_reliability.py; tests/test_medium_regressions.py; tests/test_studio.py |
| RENDER-013 through RENDER-017 | tests/test_reliability.py; tests/test_editor_server.py; tests/test_low_regressions.py; tests/test_studio.py |
| STATE-018, INTEGRATION-019, UPLOAD-020, FLOW-023 | tests/test_upload_jobs.py; tests/test_reliability.py; tests/test_browser.py |
| STATE-021, STATE-022, STATE-039 | tests/test_reliability.py; tests/test_medium_regressions.py; tests/test_low_regressions.py |
| SEC-024, SEC-025, TIME-041 | tests/test_editor_server.py; tests/test_studio.py; tests/test_low_regressions.py; tests/test_upload_jobs.py |
| INTEGRATION-026, UI-027 | tests/test_studio.py; tests/test_browser.py; TypeScript/build checks |
| LYRICS-030, CHART-031, UPLOAD-032 | tests/test_medium_regressions.py; tests/test_upload_jobs.py; uploader wrapper inspection |
| START-034, UI-035, UI-036 | tests/test_legacy_browser.py; tests/test_low_regressions.py |

## Engineering assessment

All 41 audit entries have implemented corrections or a conservative documented policy where the intended behavior was ambiguous. The local workflow is substantially more reliable and the isolated regression gate is passing. This does not establish perfect behavior or production acceptance against external services. Before unattended publication, perform a controlled acceptance check for live chart changes, lyric relevance, ASR quality, OAuth and YouTube behavior. Ambiguous upload outcomes deliberately require reconciliation instead of another insert.

The supported production path is the canonical CLI/current editor/Studio pipeline. The retained legacy editor has separate rendering assumptions; its mute/solo and state-history regressions are covered, but arbitrary interchange of its timeline schema with the current editor is not established by these tests.

## Follow-up: Render & Upload dialog settings (2026-10-09)

The user's report of edited settings reverting exposed gaps beyond the original first-upload request tests. The earlier completion assessment did not establish reliable dialog persistence or correct behavior when changing an already uploaded project.

Confirmed causes and corrections:

- The dialog sent edited fields to a job but did not persist them in `upload/youtube_metadata.json`. Reopening therefore loaded the original generated settings. Accepted job settings are now saved atomically and loaded back into the form, including privacy, schedule, category and the kids flag. The server already generated metadata only when no saved document existed; repeated generation was not the cause.
- The form restored only snake-case kids/category fields, while Studio and job snapshots could use camel-case keys. Layer-specific alias normalization now makes submitted fields override stored fields consistently, including explicit `false`, empty descriptions and empty tags. The form restores both naming conventions and prevents editing while its initial settings request is pending.
- The uploader calculated privacy before merging saved/nested metadata, and some CLI wrappers supplied `private` even when their visibility flag was omitted. Privacy and schedules now use the resolved request; omitted CLI settings leave saved values eligible.
- Duplicate protection returned the old successful upload without checking whether the requested render/settings had changed. Verified unchanged retries still reuse the old result. Changed video bytes, requested metadata or supplied thumbnails now return an explicit failure and the existing video reference, preserving the successful ledger. Historical uploads without a video hash require review when a local render is supplied. This action does not update an existing remote video or insert an accidental duplicate.
- The dialog read `error`/`upload.url`, while the status adapter returned `reason`/`youtube_url`. It now displays the actual failure reason or uploaded URL, including the explanation for an already published project.

Validation: **97 tests passed** in the host Python environment (66.71 s); **97 tests passed** in the isolated installed environment (39.22 s, one existing Starlette test-client deprecation warning). Ruff `F,E9` passed and `git diff --check` passed. No live uploads, credential changes or production-data writes were made during these tests. Frontend build inputs were unchanged; the current editor is served directly from its HTML/JavaScript.

Nine additional regression cases cover saved-setting precedence and explicit false/empty values, nested scheduling, historical upload verification, blank metadata avoidance, changed title/video/thumbnail rejection, and two actual browser-to-server-to-job-to-uploader flows (public and scheduled). In the browser flows, only FFmpeg export and Google upload are mocked; the real dialog, editor save, HTTP handler, durable queue, metadata persistence, uploader request construction and status polling execute. Both flows confirm edited settings reach the API body, survive reopening, and show a visible error for a subsequent changed-title upload.

Operational boundary: restart the editor's Python server after updating the code, then reopen/reload its browser. Existing published metadata can be edited in YouTube Studio; a separate metadata-update API feature would require a broader OAuth scope ([Google videos.update](https://developers.google.com/youtube/v3/docs/videos/update)). YouTube cannot replace the video file behind an existing URL; edited media needs a new upload ([YouTube Help](https://support.google.com/youtube/answer/55770?hl=en)). Live OAuth and publication remain untested.

## Follow-up: blank chart / empty-scrape traceback (2026-10-09)

The user reported `ValueError: Chart returned no valid songs`. Their saved raw file had zero rows and their debug page had an empty body. Anonymous read-only browser diagnostics against the configured chart URL and the site's root reproduced a blank page. Network inspection identified an HTTP 429 response from `https://charts.youtube.com/youtubei/v1/browse`, with `rateLimitExceeded` / `RESOURCE_EXHAUSTED`. The HTML document itself returned 200, so navigation success did not establish successful chart loading. This is a confirmed external chart-data failure; an obsolete route or incompatible row selector is not confirmed by this evidence. The behavior in the user's ordinary browser remains unverified.

The local defect was inadequate load/failure handling: the scraper used a fixed sleep, ignored chart-data HTTP errors, then wrote empty raw output. The refresh correctly refused to replace the database chart or complete the cycle, but surfaced a generic traceback that hid the upstream cause.

Corrections:

- Monitor chart-data response/network failures separately from analytics. Report HTTP 429 (including Retry-After when supplied), HTTP server errors, connection failures, blank-page timeouts and unparseable rows as expected chart-load failures. The CLI exits nonzero with a concise explanation, preserving the batch workflow's stop behavior.
- Wait up to 30 seconds for readable rows rather than relying on a fixed startup sleep. Keep collected rows when later scroll positions replace earlier visible rows. Use the installed Chromium identity instead of a hardcoded older browser identity.
- Count/filter valid distinct songs before applying the requested song limit; invalid candidates cannot consume that limit. Publish raw JSON atomically only after parsing yields valid songs. Failed scrapes preserve the previous raw file, database snapshot and retry eligibility; no automatic repeated requests are made after rate limiting.
- Ignore runtime lock files in Git. Redirect diagnostic cleanup paths into temporary directories in the shared test fixture so success-path tests do not clean up the user's debugging files.

Final validation: **107 tests passed** in the host environment (72.51 s). **56 focused scraper, refresh, persistence, process-recovery and medium regression tests passed** in the isolated installed environment (18.56 s). Ruff `F,E9` and `git diff --check` passed. Ten new cases exercise intercepted 429/503 responses, delayed rows, blank pages, invalid candidates and requested limits, parser failures, snapshot/retry preservation, CLI error output, analytics filtering and virtualized rows. They use intercepted browser responses, mocked requests or temporary database/filesystem state. No live chart was successfully downloaded or imported during this follow-up; live publication was not attempted.

The external 429 remains unresolved. The corrective code improves diagnosis and safe recovery; it does not establish that YouTube Charts is available or that the current live chart layout is compatible. Wait for the site to recover, check it in a regular browser, then retry the launcher (or `run.bat all --show-browser`). A controlled successful live scrape is still needed to close that integration limitation.
