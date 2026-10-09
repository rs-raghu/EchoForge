# Reliability remediation status

The audit reports retain the original baseline findings and line numbers. This register records the subsequent fixes.

## Git preservation

The audited existing code and both reports were pushed before implementation to `origin/codex/reliability-remediation` at `d748058`. Local and remote main have unrelated histories; neither was force-pushed or overwritten.

## High-priority changes

All High findings now have implemented corrections, with isolated regression coverage. The weekly policy is now a Friday-start cycle with catch-up after downtime. Chart refresh and project allocation use OS-owned locks. Invalid media, stale caches and rejected sync candidates cannot count as completed work. Rendering stages to a temporary output before atomic replacement. One durable job service handles CLI and editor requests, preserves approved metadata, and recovers interrupted owners. A shared fail-closed upload ledger prevents duplicate inserts and records ambiguous network outcomes for explicit reconciliation. Editor HTTP routes expose only public media, enforce local origin/path/resource boundaries and preserve state history. Studio now has an API and a `run.bat studio` launch command backed by the same pipeline.

The supported Studio template animations are static and fade. Unsupported animations are removed from the selector rather than silently rendered incorrectly. Playlist assignment returns an explicit unsupported-operation error because the existing upload-only OAuth scope cannot manage playlists. Studio `run_full` stops at the timing review checkpoint; it does not automatically authorize publication.

## Verification so far

- 53 automated checks passed in the complete run before adding two further cache regressions; the cache regressions also passed separately.
- Real FFmpeg audio conversion and video rendering tested in temporary projects.
- Chromium tests verify failed saves block rendering and approved title/tags/visibility reach the single job endpoint.
- Two independent Python processes refresh one weekly cycle once; a terminated worker releases its OS lock.
- Studio TypeScript checking passes; its frontend builds with the declared local dependencies (`npm ci`, no reported npm vulnerabilities).
- Live charts, lyric APIs, model downloads, OAuth, Gemini and YouTube publication have not been exercised. Production projects, secrets and databases are not test fixtures.

## Issue register

| ID | Severity | Audit title | Remediation status |
|---|---|---|---|
| LOGIC-001 | High | Weekly refresh has no missed-window recovery | Implemented; isolated regression validation |
| LOGIC-002 | High | Empty chart is recorded as successful refresh | Implemented; isolated regression validation |
| DATA-003 | Medium | Selection retains obsolete chart ranks | Pending lower-priority pass (some shared fixes already landed) |
| DATA-004 | High | Unicode identities collide and silently drop songs | Implemented; isolated regression validation |
| STATE-005 | High | Song claims and project allocation are not exclusive | Implemented; isolated regression validation |
| CONFIG-006 | Medium | Environment loading and credential names disagree | Pending lower-priority pass (some shared fixes already landed) |
| MEDIA-007 | High | Invalid audio can be accepted as normalized success | Implemented; isolated regression validation |
| MEDIA-008 | Medium | Force-normalize uses the same input and output | Pending lower-priority pass (some shared fixes already landed) |
| STATE-009 | High | Artifact caches ignore validity and input changes | Implemented; isolated regression validation |
| SYNC-010 | High | Failed transfer overwrites approved final lyrics | Implemented; isolated regression validation |
| SYNC-011 | Medium | Invalid existing LRC prevents automatic fallback | Pending lower-priority pass (some shared fixes already landed) |
| SYNC-012 | Medium | Lyric JSON and LRC parser contracts diverge | Pending lower-priority pass (some shared fixes already landed) |
| RENDER-013 | High | Prepare then render omits declared background | Implemented; isolated regression validation |
| RENDER-014 | High | Export differs from approved visual/audio edits | Implemented; isolated regression validation |
| RENDER-015 | Medium | Missing clips produce invalid FFmpeg input indices | Pending lower-priority pass (some shared fixes already landed) |
| RENDER-016 | High | FFmpeg stderr can deadlock long renders | Implemented; isolated regression validation |
| RENDER-017 | Low | Module entry executes before helper definitions | Pending lower-priority pass (some shared fixes already landed) |
| STATE-018 | High | Running jobs permanently block after restart | Implemented; isolated regression validation |
| INTEGRATION-019 | High | Render modal discards approved metadata and schedule | Implemented; isolated regression validation |
| UPLOAD-020 | High | Primary upload bypasses duplicate protection | Implemented; isolated regression validation |
| STATE-021 | High | State writers destroy or contradict workflow history | Implemented; isolated regression validation |
| STATE-022 | Medium | Failed upload report is displayed as uploaded | Pending lower-priority pass (some shared fixes already landed) |
| FLOW-023 | High | Workflow continues failures and chooses a previous project | Implemented; isolated regression validation |
| SEC-024 | High | Root media route exposes credential files | Implemented; isolated regression validation |
| SEC-025 | High | Untrusted paths and unbounded renders lack constraints | Implemented; isolated regression validation |
| INTEGRATION-026 | High | Studio has no compatible backend in repository | Implemented; isolated regression validation |
| UI-027 | Medium | Studio async responses can lose or misroute edits | Pending lower-priority pass (some shared fixes already landed) |
| BUILD-028 | Medium | Declared Python minimum cannot parse metadata generator | Pending lower-priority pass (some shared fixes already landed) |
| DB-029 | Medium | SQLite transaction contexts do not close connections | Pending lower-priority pass (some shared fixes already landed) |
| LYRICS-030 | Medium | Search normalization removes x within words | Pending lower-priority pass (some shared fixes already landed) |
| CHART-031 | Medium | Numeric titles are treated as metrics | Pending lower-priority pass (some shared fixes already landed) |
| UPLOAD-032 | Medium | Privacy alias is ignored by default visibility | Pending lower-priority pass (some shared fixes already landed) |
| TIME-033 | Medium | Refresh completion uses host calendar zone | Pending lower-priority pass (some shared fixes already landed) |
| START-034 | Low | Launcher hardcodes obsolete checkout path | Pending lower-priority pass (some shared fixes already landed) |
| UI-035 | Medium | First legacy Shift-click uses undeclared selection variable | Pending lower-priority pass (some shared fixes already landed) |
| UI-036 | Low | Legacy mute/solo controls do not affect audio | Pending lower-priority pass (some shared fixes already landed) |
| QA-037 | Medium | Automated regression test files are empty | Pending lower-priority pass (some shared fixes already landed) |
| BUILD-038 | Medium | Package omits direct runtime dependency declaration | Pending lower-priority pass (some shared fixes already landed) |
| STATE-039 | Medium | JSON state writes are not crash-safe | Pending lower-priority pass (some shared fixes already landed) |
| SYNC-040 | Medium | Timing quality acceptance is underspecified | Pending lower-priority pass (some shared fixes already landed) |
| TIME-041 | High | Past or timezone-naive publish times are forwarded unchecked | Implemented; isolated regression validation |
