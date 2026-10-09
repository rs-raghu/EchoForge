# Reliability remediation status

The audit reports retain the original baseline findings and line numbers. This register records the subsequent fixes.

## Git preservation

The audited existing code and both reports were pushed before implementation to `origin/codex/reliability-remediation` at `d748058`. Local and remote main have unrelated histories; neither was force-pushed or overwritten.

## High-priority changes

All High findings now have implemented corrections, with isolated regression coverage. The weekly policy is now a Friday-start cycle with catch-up after downtime. Chart refresh and project allocation use OS-owned locks. Invalid media, stale caches and rejected sync candidates cannot count as completed work. Rendering stages to a temporary output before atomic replacement. One durable job service handles CLI and editor requests, preserves approved metadata, and recovers interrupted owners. A shared fail-closed upload ledger prevents duplicate inserts and records ambiguous network outcomes for explicit reconciliation. Editor HTTP routes expose only public media, enforce local origin/path/resource boundaries and preserve state history. Studio now has an API and a `run.bat studio` launch command backed by the same pipeline.

The supported Studio template animations are static and fade. Unsupported animations are removed from the selector rather than silently rendered incorrectly. Playlist assignment returns an explicit unsupported-operation error because the existing upload-only OAuth scope cannot manage playlists. Studio `run_full` stops at the timing review checkpoint; it does not automatically authorize publication.

## Verification so far

- 74 automated checks passed in both the host environment and a fresh Python 3.13 environment; a further legacy Shift-click browser regression passed separately.
- Real FFmpeg audio conversion and video rendering tested in temporary projects.
- Chromium tests verify failed saves block rendering and approved title/tags/visibility reach the single job endpoint.
- Two independent Python processes refresh one weekly cycle once; a terminated worker releases its OS lock.
- Studio TypeScript checking passes; its frontend builds with the declared local dependencies (`npm ci`, no reported npm vulnerabilities).
- Live charts, lyric APIs, model downloads, OAuth, Gemini and YouTube publication have not been exercised. Production projects, secrets and databases are not test fixtures.

## Medium-priority changes

All Medium findings now have corrections or an explicit documented acceptance policy. Current chart membership is stored transactionally without removing history. Environment loading occurs before settings evaluation; credential aliases resolve consistently. Shared LRC parsing handles offsets, multiple tags and blank interval boundaries. Editors are keyed by project, serialize requests, preserve newer dirty revisions, and disable metadata/design edits while mutations are pending. Failed upload reports cannot imply success. Canonical JSON writes use atomic replacement, stage updates merge under a shared lock, complete sync operations serialize across workers, and paired timing publication has a completion manifest. Direct runtime dependencies and optional capabilities are declared in the package; regression checks have a CI workflow.

Validation: 18 new Medium regressions passed, delayed-save and repeat-metadata-save Chromium checks passed, legacy first Shift-click/range selection passed, both frontend builds passed, Studio TypeScript passed, Ruff F/E9 passed, Python 3.10 syntax parsing passed, and a fresh Python 3.13 install/import/pip-check/full-suite run passed. That fresh environment emitted one Starlette test-client deprecation warning; no functional failures occurred. CI execution and a Python 3.10 runtime run are still distinct verification steps.

See [testing instructions and operational policies](../docs/RELIABILITY_TESTING.md). The timing-quality and current-chart ambiguities are resolved conservatively in code and documented, without claiming external lyric/ASR correctness.

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
| RENDER-017 | Low | Module entry executes before helper definitions | Pending lower-priority pass (some shared fixes already landed) |
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
| START-034 | Low | Launcher hardcodes obsolete checkout path | Pending lower-priority pass (some shared fixes already landed) |
| UI-035 | Medium | First legacy Shift-click uses undeclared selection variable | Implemented; regression checks and documented policy |
| UI-036 | Low | Legacy mute/solo controls do not affect audio | Pending lower-priority pass (some shared fixes already landed) |
| QA-037 | Medium | Automated regression test files are empty | Implemented; regression checks and documented policy |
| BUILD-038 | Medium | Package omits direct runtime dependency declaration | Implemented; regression checks and documented policy |
| STATE-039 | Medium | JSON state writes are not crash-safe | Implemented; regression checks and documented policy |
| SYNC-040 | Medium | Timing quality acceptance is underspecified | Implemented; regression checks and documented policy |
| TIME-041 | High | Past or timezone-naive publish times are forwarded unchecked | Implemented; isolated regression validation |
