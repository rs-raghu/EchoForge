# AUDIT 02 — Debugging, logical errors and reliability

## 1. Executive Summary

Repository root verified with Git: `D:\Hello World\2. Automations\EchoForge`. Audit date: 2026-10-09; user timezone Asia/Calcutta. Source and declarative files are the primary evidence. No source fixes, dependency installs/upgrades, migrations, deletions, real downloads, uploads or billable model requests were performed. Only these two repository reports are created.

Discovery found **311 tracked files**, including **133 historical migration snapshots** and **3 tracked Studio build outputs** excluded from detailed source review. Adding **24 installed first-party image assets** and **one private .env key inventory** gives **200 relevant files in 49 relevant folders (including root)**. **199 relevant files are fully inspected for their applicable source/declarative/asset responsibilities; .env is partially inspected (keys only). Zero relevant source files are unread or inaccessible.** There are 62 verified zero-byte files: empty scaffolds are documented, not treated as implemented features. Secret file contents are deliberately outside scope.

“Reviewed” is a static/contract inspection status, not a correctness or test-pass claim. For assets it means metadata/decoding/font loading; for PDF it means full two-page text. “Tests Reviewed” means testability, available tests and missing cases examined; it does not imply every file was executed. Dynamic integrations remain limited as specified below.

**Release assessment: not ready for unattended production use.** The audit identifies **41 grouped findings**: **0 confirmed Critical, 14 confirmed High, 15 confirmed Medium, 3 confirmed Low**, and **9 additional high-confidence risks or requirement ambiguities**. Confidence reflects evidence, independently of severity. A confirmed static defect is not automatically a witnessed production incident.

Validation includes **32 isolated behavioral tests: 9 passed, 23 failed, 0 harness errors** after correcting fixture cleanup; **3 browser contract assertions: all 3 failed** with all requests mocked; and **30 image/font checks: all passed**. Thus the explicitly counted behavioral/browser/asset checks total **65: 39 passed, 26 failed, 0 finally blocked within those fixtures**. Two expected-behavior assertions (missed-Friday catch-up and fresh-only selection) depend on requirements; those are not counted as confirmed product defects. Additional blocked live-validation categories and static-tool results are detailed separately.

The most consequential confirmed failures are private-file serving, repeat-upload bypass, approved render metadata being dropped, failed synchronization overwriting final output, and workerless persisted jobs blocking recovery. State/schema and preview/export disagreements can produce wrong results despite successful execution.

## 2. Overall Engineering Assessment

The codebase is a workable manually operated prototype with accumulated migration/compatibility patches. A current-Python help/import path and tiny FFmpeg export succeed; the actual SQLite database is structurally readable. Those observations do not validate the important contracts: intended source song, approved timeline/metadata, exactly-once publication, completion persistence or restart recovery.

Risk is concentrated at stage boundaries and competing implementations. Empty test scaffolds and incomplete Studio integration leave no checked-in regression safety net. Several implementation comments describe safety features that apply only to an alternative path. Confirmed source facts are distinguished from inferred product requirements and unexecuted concurrency/soak hypotheses throughout.

## 3. Issue Summary Table

| ID | Severity | File | Issue | Impact | Confidence | Fix Priority |
|---|---|---|---|---|---|---|

| LOGIC-001 | High | `src/echoforge/stages/songscout/policy.py:56` | Weekly refresh has no missed-window recovery | Stale charts and non-Friday inability to initialize an empty database. | Requires specification clarification | Specification decision then risk-ranked correction |

| LOGIC-002 | High | `src/echoforge/cli.py:63`, `src/echoforge/orchestrator.py:105` | Empty chart is recorded as successful refresh | False completion preserves stale data and blocks recovery. | Confirmed | P1 before production |

| DATA-003 | Medium | `src/echoforge/stages/songscout/database.py:295`, `src/echoforge/stages/songscout/database.py:157` | Selection retains obsolete chart ranks | Off-chart output if current-chart intent; backlog semantics are unspecified. | Requires specification clarification | Specification decision then risk-ranked correction |

| DATA-004 | High | `src/echoforge/stages/songscout/cleaner.py:15`, `src/echoforge/stages/songscout/cleaner.py:132` | Unicode identities collide and silently drop songs | Silent song loss and wrong source/project association. | Confirmed | P1 before production |

| STATE-005 | High | `src/echoforge/stages/songscout/database.py:285`, `src/echoforge/core/project_builder.py:261`, `src/echoforge/core/project_builder.py:288` | Song claims and project allocation are not exclusive | Duplicate processing, conflicting project IDs and lost state. | High confidence | P1 before production |

| CONFIG-006 | Medium | `src/echoforge/core/config.py:9`, `src/echoforge/stages/musevault/genius_lyrics.py:24`, `src/echoforge/stages/tubeharbor/youtube_uploader.py:15`, `scripts/youtube_upload_project.py:41` | Environment loading and credential names disagree | Wrong settings and avoidable authentication failures. | Confirmed | P2 before scale/release |

| MEDIA-007 | High | `src/echoforge/stages/musevault/audio_normalizer.py:66`, `src/echoforge/stages/musevault/audio_service.py:25` | Invalid audio can be accepted as normalized success | Whisper/render fail after assets were reported ready. | Confirmed | P1 before production |

| MEDIA-008 | Medium | `src/echoforge/stages/musevault/audio_normalizer.py:71`, `src/echoforge/stages/musevault/audio_normalizer.py:60` | Force-normalize uses the same input and output | FFmpeg refuses; recovery option fails. | Confirmed | P2 before scale/release |

| STATE-009 | High | `src/echoforge/stages/verselock/synced_reuse.py:120`, `src/echoforge/stages/verselock/whisper_advanced.py:211`, `src/echoforge/stages/verselock/whisper_advanced.py:214` | Artifact caches ignore validity and input changes | Incorrect lyrics/timings reach editor and export. | Confirmed | P1 before production |

| SYNC-010 | High | `src/echoforge/stages/verselock/timestamp_transfer.py:352`, `src/echoforge/stages/verselock/timestamp_transfer.py:353`, `src/echoforge/stages/verselock/sync_runner.py:249` | Failed transfer overwrites approved final lyrics | Rejected timing is rendered while state says needs_review. | Confirmed | P1 before production |

| SYNC-011 | Medium | `src/echoforge/stages/verselock/sync_runner.py:235`, `src/echoforge/stages/verselock/synced_reuse.py:107` | Invalid existing LRC prevents automatic fallback | Recovery requires manual file intervention or explicit mode. | Confirmed | P2 before scale/release |

| SYNC-012 | Medium | `src/echoforge/stages/renderer/editor_project_v2.py:83`, `src/echoforge/stages/verselock/lrc_parser.py:15`, `src/echoforge/stages/renderer/editor_project_v2.py:52` | Lyric JSON and LRC parser contracts diverge | Missing or inconsistent lyric timelines; usual LRC fallback masks mismatch. | Confirmed | P2 before scale/release |

| RENDER-013 | High | `src/echoforge/stages/renderer/editor_project_builder.py:520`, `src/echoforge/stages/renderer/exporter.py:70`, `src/echoforge/stages/renderer/exporter.py:132` | Prepare then render omits declared background | Successful MP4 has wrong white background. | Confirmed | P1 before production |

| RENDER-014 | High | `src/echoforge/stages/renderer/exporter.py:221`, `src/echoforge/stages/renderer/exporter.py:152`, `src/echoforge/stages/renderer/exporter.py:268` | Export differs from approved visual/audio edits | Unwanted media/text can be published and approval becomes unreliable. | Confirmed | P1 before production |

| RENDER-015 | Medium | `src/echoforge/stages/renderer/exporter.py:226`, `src/echoforge/stages/renderer/exporter.py:228`, `src/echoforge/stages/renderer/exporter.py:230` | Missing clips produce invalid FFmpeg input indices | Audio timeline fails unnecessarily. | Confirmed | P2 before scale/release |

| RENDER-016 | High | `src/echoforge/stages/renderer/exporter.py:263`, `src/echoforge/stages/renderer/exporter.py:283`, `src/echoforge/stages/renderer/exporter.py:286` | FFmpeg stderr can deadlock long renders | Permanent running job and held resources. | High confidence | P1 before production |

| RENDER-017 | Low | `src/echoforge/stages/renderer/exporter.py:300`, `src/echoforge/stages/renderer/exporter.py:312` | Module entry executes before helper definitions | Alternate executable path fails. | Confirmed | P3 maintenance |

| STATE-018 | High | `src/echoforge/stages/renderer/render_jobs.py:17`, `src/echoforge/stages/renderer/render_jobs.py:47`, `scripts/render_upload_project.py:75` | Running jobs permanently block after restart | Manual state intervention required; daemon work lost. | Confirmed | P1 before production |

| INTEGRATION-019 | High | `apps/webeditor/index.html:633`, `scripts/open_webeditor.py:120`, `scripts/open_webeditor.py:393`, `scripts/render_upload_project.py:67` | Render modal discards approved metadata and schedule | User approval ignored; upload skipped or schedule lost. | Confirmed | P1 before production |

| UPLOAD-020 | High | `scripts/run_router.py:65`, `scripts/youtube_upload_project.py:94`, `src/echoforge/stages/tubeharbor/upload_db.py:12`, `src/echoforge/stages/tubeharbor/youtube_uploader.py:59` | Primary upload bypasses duplicate protection | Duplicate videos, quota and ambiguous history. | Confirmed | P1 before production |

| STATE-021 | High | `apps/webeditor_legacy/backend/main.py:634`, `scripts/mark_project_uploaded.py:117`, `src/echoforge/core/project_builder.py:251` | State writers destroy or contradict workflow history | Wrong source downloads and unreconcilable completion state. | Confirmed | P1 before production |

| STATE-022 | Medium | `scripts/project_status.py:67`, `scripts/youtube_upload_project.py:112` | Failed upload report is displayed as uploaded | User trusts nonexistent publication or stops retrying. | Confirmed | P2 before scale/release |

| FLOW-023 | High | `scripts/workflow_all.py:89`, `scripts/workflow_all.py:106`, `scripts/render_project.py:7`, `src/echoforge/stages/renderer/exporter.py:299`, `apps/webeditor/app.js:642` | Workflow continues failures and chooses a previous project | Wrong project, lost timeline or stale video published. | Confirmed | P1 before production |

| SEC-024 | High | `scripts/open_webeditor.py:488`, `scripts/open_webeditor.py:490` | Root media route exposes credential files | OAuth/API credential disclosure; public bind increases risk. | Confirmed | P0 before exposed use |

| SEC-025 | High | `src/echoforge/stages/renderer/exporter.py:38`, `src/echoforge/stages/renderer/exporter.py:248`, `src/echoforge/stages/renderer/webeditor_server.py:190`, `scripts/open_webeditor.py:528` | Untrusted paths and unbounded renders lack constraints | Disclosure, unintended overwrite or CPU/disk exhaustion; default loopback limits reach. | High confidence | P1 before production |

| INTEGRATION-026 | High | `apps/web-studio/frontend/src/api.ts:43`, `apps/web-studio/frontend/src/api.ts:59`, `apps/webeditor_legacy/backend/main.py:1274` | Studio has no compatible backend in repository | Studio feature set is inoperable with included services. | Confirmed | P1 before production |

| UI-027 | Medium | `apps/web-studio/frontend/src/editors/LyricsEditor.tsx:178`, `apps/web-studio/frontend/src/editors/LyricsEditor.tsx:35`, `apps/web-studio/frontend/src/editors/SyncEditor.tsx:245`, `apps/web-studio/frontend/src/views/UploadManagerView.tsx:27` | Studio async responses can lose or misroute edits | Lost edits or cross-project writes if compatible backend is deployed. | High confidence | P2 before scale/release |

| BUILD-028 | Medium | `pyproject.toml:5`, `src/echoforge/stages/tubeharbor/metadata_generator.py:374` | Declared Python minimum cannot parse metadata generator | Startup/metadata SyntaxError on supported runtime. | Confirmed | P2 before scale/release |

| DB-029 | Medium | `src/echoforge/stages/songscout/database.py:122`, `src/echoforge/stages/songscout/database.py:53` | SQLite transaction contexts do not close connections | Resource accumulation and Windows maintenance/cleanup problems. | Confirmed | P2 before scale/release |

| LYRICS-030 | Medium | `src/echoforge/stages/musevault/metadata_review.py:62` | Search normalization removes x within words | Missing/wrong lyrics. | Confirmed | P2 before scale/release |

| CHART-031 | Medium | `src/echoforge/stages/songscout/cleaner.py:80`, `src/echoforge/stages/songscout/cleaner.py:102` | Numeric titles are treated as metrics | Silent chart omission/incorrect identity. | Confirmed | P2 before scale/release |

| UPLOAD-032 | Medium | `scripts/youtube_upload_project.py:72`, `scripts/youtube_upload_project.py:136` | Privacy alias is ignored by default visibility | Video visibility differs from command; schedule alias ignored. | Confirmed | P2 before scale/release |

| TIME-033 | Medium | `src/echoforge/stages/songscout/database.py:362`, `src/echoforge/stages/songscout/policy.py:14` | Refresh completion uses host calendar zone | Duplicate refresh around midnight. | Confirmed | P2 before scale/release |

| START-034 | Low | `start_echoforge.bat:3` | Launcher hardcodes obsolete checkout path | Failure or wrong code/data launched. | Confirmed | P3 maintenance |

| UI-035 | Medium | `apps/webeditor_legacy/frontend/src/main.jsx:671`, `apps/webeditor_legacy/frontend/src/main.jsx:734` | First legacy Shift-click uses undeclared selection variable | ReferenceError aborts selection. | Confirmed | P2 before scale/release |

| UI-036 | Low | `apps/webeditor_legacy/frontend/src/main.jsx:673`, `apps/webeditor_legacy/frontend/src/main.jsx:923` | Legacy mute/solo controls do not affect audio | Misleading audio approval. | Confirmed | P3 maintenance |

| QA-037 | Medium | `tests/test_workflow.py (empty; no line)`, `tests/test_musevault.py (empty; no line)`, `tests/test_songscout.py (empty; no line)`, `tests/test_verselock.py (empty; no line)` | Automated regression test files are empty | No automated reliability assurance. | Confirmed | P2 before scale/release |

| BUILD-038 | Medium | `pyproject.toml:1`, `requirements.txt:2` | Package omits direct runtime dependency declaration | Deployment startup failure; host success cannot prove clean compatibility. | Confirmed | P2 before scale/release |

| STATE-039 | Medium | `src/echoforge/stages/tubeharbor/upload_db.py:17`, `src/echoforge/stages/renderer/render_jobs.py:24`, `src/echoforge/core/project_builder.py:112` | JSON state writes are not crash-safe | Lost history, reopened guard and inconsistent manifests. | High confidence | P2 before scale/release |

| SYNC-040 | Medium | `src/echoforge/stages/verselock/timestamp_transfer.py:352`, `src/echoforge/stages/verselock/timestamp_transfer.py:346`, `src/echoforge/stages/verselock/timestamp_transfer.py:348` | Timing quality acceptance is underspecified | Plausible but wrong timing may be accepted; quality tolerance ambiguous. | Requires specification clarification | Specification decision then risk-ranked correction |

| TIME-041 | High | `scripts/youtube_upload_project.py:80`, `src/echoforge/stages/tubeharbor/youtube_uploader.py:66` | Past or timezone-naive publish times are forwarded unchecked | Potential unexpectedly public video instead of deferred release. Live publication was not exercised. | High confidence | P1 before production |


## 4. Critical Issues

No Critical defect is asserted. Default loopback binding and the untested scope of external exploitation do not justify labeling the confirmed root-file disclosure as universally Critical. It is High and should be closed before exposing the editor or relying on credential isolation.


## 5. High-Severity Issues


### LOGIC-001 — Weekly refresh has no missed-window recovery

**Issue ID:** LOGIC-001  
**Severity:** High  
**Confidence:** Requires specification clarification  
**Affected files:** `src/echoforge/stages/songscout/policy.py:56`

**Intended behavior:** If Friday begins a weekly window, complete any outstanding current cycle on the next execution. The repository explicitly documents Friday-only scraping, so strict-day versus catch-up is a product decision.

**Actual behavior:** Saturday skips even with last success the previous Friday or no success.

**Root cause:** Weekday and exact today comparison replace a persisted cycle identifier.

**Failure scenario:** Offline Friday; restart Saturday with last success 2026-10-02; wait another week or force manually.

**Impact:** Stale charts and non-Friday inability to initialize an empty database.

**Reproduction steps:** Freeze today_local to 2026-10-10 and metadata date to 2026-10-02; call should_scrape_today.

**Evidence:** test_saturday_missed failed: False. The behavior is confirmed; a catch-up requirement is not independently documented.

- `src/echoforge/stages/songscout/policy.py:56` — `if now.weekday() != FRIDAY:`

**Recommended fix:** Specify policy; if catch-up is required, use configured-zone Friday cycle IDs and persist only validated completion.

**Regression tests:** Friday pending, missed Saturday, completed Sunday, failure/interruption, next Friday, midnight and two workers.

**Dependencies:** CLI, orchestrator, refresh metadata and selection.

### LOGIC-002 — Empty chart is recorded as successful refresh

**Issue ID:** LOGIC-002  
**Severity:** High  
**Confidence:** Confirmed  
**Affected files:** `src/echoforge/cli.py:63`, `src/echoforge/orchestrator.py:105`

**Intended behavior:** Only a validated usable chart completes refresh.

**Actual behavior:** Zero raw/clean songs still lead to success recording.

**Root cause:** No valid-row/completeness gate before persistence.

**Failure scenario:** Chart DOM changes; cleaner returns []; success date suppresses the next Friday retry.

**Impact:** False completion preserves stale data and blocks recovery.

**Reproduction steps:** Mock scrape to []; spy on recorder and upsert in both refresh implementations; never use production DB.

**Evidence:** Unconditional source sequence; this specific mocked refresh was specified but not executed.

- `src/echoforge/cli.py:63` — `record_scrape_result(success=True, row_count=len(raw_rows), clean_count=len(clean_songs), reason=decision.reason)`
- `src/echoforge/orchestrator.py:105` — `record_scrape_result(success=True, row_count=len(raw_rows), clean_count=len(clean_songs), reason=decision.reason)`

**Recommended fix:** Reject empty or implausible snapshots, retain last good chart and record a retriable failure.

**Regression tests:** Empty, all-invalid, unexpectedly partial, good snapshot and subsequent successful retry.

**Dependencies:** Scraper, cleaner, database and duplicate refresh implementations.

### DATA-004 — Unicode identities collide and silently drop songs

**Issue ID:** DATA-004  
**Severity:** High  
**Confidence:** Confirmed  
**Affected files:** `src/echoforge/stages/songscout/cleaner.py:15`, `src/echoforge/stages/songscout/cleaner.py:132`

**Intended behavior:** Distinct supported-language title/artist pairs require stable distinct identities.

**Actual behavior:** Fully non-Latin pairs normalize to the same :: hash input.

**Root cause:** ASCII presentation slug is reused as identity.

**Failure scenario:** Two Hindi songs/artists collapse; dedup drops one or upsert overwrites its row.

**Impact:** Silent song loss and wrong source/project association.

**Reproduction steps:** Call unique_song_id on both Devanagari fixture pairs.

**Evidence:** test_unicode_ids_unique failed: both 71546855d6279ef7.

- `src/echoforge/stages/songscout/cleaner.py:15` — `_RE_NON_ALPHANUM = re.compile(r"[^a-z0-9]+")`
- `src/echoforge/stages/songscout/cleaner.py:132` — `base = f"{normalize_key(title)}::{normalize_key(artist)}"`

**Recommended fix:** Hash normalized Unicode casefolded identity or stable source ID; migrate collisions with source evidence.

**Regression tests:** Hindi, Korean, Arabic, mixed scripts, punctuation variants and re-entry.

**Dependencies:** Cleaner dedup, SQLite primary key, song_id and project reuse.

### STATE-005 — Song claims and project allocation are not exclusive

**Issue ID:** STATE-005  
**Severity:** High  
**Confidence:** High confidence  
**Affected files:** `src/echoforge/stages/songscout/database.py:285`, `src/echoforge/core/project_builder.py:261`, `src/echoforge/core/project_builder.py:288`

**Intended behavior:** Atomically claim one song and allocate one unique project per worker.

**Actual behavior:** Read, file creation, status marking and number advancement are separate operations; refresh eligibility is also read-only.

**Root cause:** No conditional transactional claim or unique durable project allocation.

**Failure scenario:** Two workers read the same song/counter then overwrite the same folder/state.

**Impact:** Duplicate processing, conflicting project IDs and lost state.

**Reproduction steps:** Barrier two isolated workers after selection/counter read, then release; use temp DB/project roots.

**Evidence:** Two eligibility decisions both True (test_two_workers_exclusive failed 2 != 1). Actual multi-process project race not executed.

- `src/echoforge/stages/songscout/database.py:285` — `def get_next_available_song(include_failed: bool = False) -> dict[str, Any] | None:`
- `src/echoforge/core/project_builder.py:261` — `project_number = get_next_project_number()`
- `src/echoforge/core/project_builder.py:288` — `advance_project_number(project_number)`

**Recommended fix:** Use SQLite conditional claims/unique allocation in an immediate transaction; durable leases and atomic project finalization.

**Regression tests:** Two workers, interrupted owner, claim expiry, different songs and allocation recovery.

**Dependencies:** Database, selector, project_builder, CLI and orchestrator.

### MEDIA-007 — Invalid audio can be accepted as normalized success

**Issue ID:** MEDIA-007  
**Severity:** High  
**Confidence:** Confirmed  
**Affected files:** `src/echoforge/stages/musevault/audio_normalizer.py:66`, `src/echoforge/stages/musevault/audio_service.py:25`

**Intended behavior:** Reuse valid decodable audio for the current source.

**Actual behavior:** Empty m4a is ok=True; source identity/decodability are not established by reuse shortcuts.

**Root cause:** Existence-based acceptance and direct final conversion output.

**Failure scenario:** Interrupted conversion leaves partial m4a; restart prioritizes it over valid mp3.

**Impact:** Whisper/render fail after assets were reported ready.

**Reproduction steps:** Create empty audio/source_audio.m4a in temp project; normalize.

**Evidence:** test_zero_byte_audio_rejected failed: ok=True.

- `src/echoforge/stages/musevault/audio_normalizer.py:66` — `if target.exists() and source.resolve() == target.resolve() and not force:`
- `src/echoforge/stages/musevault/audio_service.py:25` — `def download_audio(project_dir: Path, review: dict[str, Any]) -> dict[str, Any]:`

**Recommended fix:** Probe content/duration and input fingerprint; convert to temp output, validate and atomically replace.

**Regression tests:** Empty, truncated, changed URL, bad m4a plus good mp3 and interrupted conversion.

**Dependencies:** Collector, validator, Whisper and renderer.

### STATE-009 — Artifact caches ignore validity and input changes

**Issue ID:** STATE-009  
**Severity:** High  
**Confidence:** Confirmed  
**Affected files:** `src/echoforge/stages/verselock/synced_reuse.py:120`, `src/echoforge/stages/verselock/whisper_advanced.py:211`, `src/echoforge/stages/verselock/whisper_advanced.py:214`

**Intended behavior:** Resume only valid completed outputs for current lyrics/audio/model.

**Actual behavior:** Old LRC plus malformed JSON are reused successfully; Whisper cache assumes ok=True without original quality gate/input fingerprint.

**Root cause:** Existence is the cache key and completion criterion.

**Failure scenario:** Lyrics/audio changes or partial write; restart returns stale/corrupt success.

**Impact:** Incorrect lyrics/timings reach editor and export.

**Reproduction steps:** Seed new input LRC, old final LRC and final JSON containing {; reuse without force.

**Evidence:** test_sync_corrupt_outputs_rebuilt failed: reused_existing_outputs=True.

- `src/echoforge/stages/verselock/synced_reuse.py:120` — `if output_lrc.exists() and output_json.exists() and not force:`
- `src/echoforge/stages/verselock/whisper_advanced.py:211` — `if output_json.exists() and output_word_lrc.exists() and not force:`
- `src/echoforge/stages/verselock/whisper_advanced.py:214` — `ok=True,`

**Recommended fix:** Validate outputs and quality; fingerprint dependencies; publish paired outputs and completion manifest atomically.

**Regression tests:** Changed inputs/model, truncated JSON, one missing output, sparse transcript and good restart.

**Dependencies:** Audio/lyric caches, Whisper, sync runner and editor preparation.

### SYNC-010 — Failed transfer overwrites approved final lyrics

**Issue ID:** SYNC-010  
**Severity:** High  
**Confidence:** Confirmed  
**Affected files:** `src/echoforge/stages/verselock/timestamp_transfer.py:352`, `src/echoforge/stages/verselock/timestamp_transfer.py:353`, `src/echoforge/stages/verselock/sync_runner.py:249`

**Intended behavior:** Failed alignment preserves accepted final output.

**Actual behavior:** ok=False still writes finals whenever promote=True; fallback explicitly promotes.

**Root cause:** Promotion is independent of acceptance.

**Failure scenario:** Approved final exists; one-segment sparse skeleton fails but replaces final.

**Impact:** Rejected timing is rendered while state says needs_review.

**Reproduction steps:** Temp project: GOOD APPROVED FINAL, official lyric, one segment; transfer with promote/use_segments True.

**Evidence:** test_failed_transfer_preserves_final failed: final became [00:01.00] official lyric with ok=False.

- `src/echoforge/stages/verselock/timestamp_transfer.py:352` — `ok = len(transferred) > 0 and len(whisper_lines) >= max(8, int(len(lyric_lines) * 0.55))`
- `src/echoforge/stages/verselock/timestamp_transfer.py:353` — `output_lrc = final_lrc if promote else candidate_lrc`
- `src/echoforge/stages/verselock/sync_runner.py:249` — `promote=True,`

**Recommended fix:** Write candidates first; promote only accepted/reviewed results with atomic replacement.

**Regression tests:** Sparse/unrelated skeleton, prior finals, partial writes and explicit approved promotion.

**Dependencies:** Sync runner, alignment safety policy, editor and final JSON/LRC.

### RENDER-013 — Prepare then render omits declared background

**Issue ID:** RENDER-013  
**Severity:** High  
**Confidence:** Confirmed  
**Affected files:** `src/echoforge/stages/renderer/editor_project_builder.py:520`, `src/echoforge/stages/renderer/exporter.py:70`, `src/echoforge/stages/renderer/exporter.py:132`

**Intended behavior:** Supported prepare-render command exports configured artwork.

**Actual behavior:** Stage-one has assets plus lyric-only clips; exporter only consumes clips and draws white.

**Root cause:** Producer/consumer media-timeline mismatch.

**Failure scenario:** Root renderer prepare then render without opening V2 editor.

**Impact:** Successful MP4 has wrong white background.

**Reproduction steps:** Pass actual stage-one shape with red fixture background to clips_from/background_at.

**Evidence:** test_stage1_background_visible failed: white pixel; small real encode separately passed.

- `src/echoforge/stages/renderer/editor_project_builder.py:520` — `"clips": clips,`
- `src/echoforge/stages/renderer/exporter.py:70` — `if isinstance(project.get("clips"), list): return project["clips"]`
- `src/echoforge/stages/renderer/exporter.py:132` — `if not active: return Image.new("RGB", size, (255,255,255))`

**Recommended fix:** Produce canonical media tracks or explicitly adapt stage-one assets.

**Regression tests:** Direct prepare-render, V2 render, custom/missing background and gaps.

**Dependencies:** Router, builders, exporter and renderer docs.

### RENDER-014 — Export differs from approved visual/audio edits

**Issue ID:** RENDER-014  
**Severity:** High  
**Confidence:** Confirmed  
**Affected files:** `src/echoforge/stages/renderer/exporter.py:221`, `src/echoforge/stages/renderer/exporter.py:152`, `src/echoforge/stages/renderer/exporter.py:268`

**Intended behavior:** Export preserves saved pixel positions, removed/hidden clips, volume and supported styles.

**Actual behavior:** Deleting all audio restores source; x=50 becomes 960 at width 1920. Visibility/opacity/font-family/volume are not consistently consumed.

**Root cause:** Heuristic coordinate units, unconditional media fallback and incomplete editable-field support.

**Failure scenario:** Delete audio or hide lyrics; position near edge or choose font; final differs from preview.

**Impact:** Unwanted media/text can be published and approval becomes unreliable.

**Reproduction steps:** build_audio([], existing source); pos(50,1920,960); trace style consumers against app.js.

**Evidence:** Two fixtures failed: deleted audio returns source; x=50 returns 960. Other omitted fields verified statically.

- `src/echoforge/stages/renderer/exporter.py:221` — `if not ac: return fallback if fallback.exists() else None`
- `src/echoforge/stages/renderer/exporter.py:152` — `if 1<x<=100: return int((x/100)*total)`
- `src/echoforge/stages/renderer/exporter.py:268` — `for c in [x for x in clips if clip_type(x)=="lyric" and start(x)<=t<end(x)]:`

**Recommended fix:** Explicit unit/capability schema; implement advertised fields; canonical absence of audio means silence.

**Regression tests:** Deleted/muted audio, hidden/transparent text, x/y=0,1,50,100, fonts and preview/export parity.

**Dependencies:** Editor models, both renderers and audio mixing.

### RENDER-016 — FFmpeg stderr can deadlock long renders

**Issue ID:** RENDER-016  
**Severity:** High  
**Confidence:** High confidence  
**Affected files:** `src/echoforge/stages/renderer/exporter.py:263`, `src/echoforge/stages/renderer/exporter.py:283`, `src/echoforge/stages/renderer/exporter.py:286`

**Intended behavior:** Drain child output while feeding frames with bounded recovery.

**Actual behavior:** stderr pipe is read only after all frame writes.

**Root cause:** Two bounded pipes can mutually block; no watchdog.

**Failure scenario:** Warning-heavy/long encode fills stderr; FFmpeg stops stdin reads and writer blocks.

**Impact:** Permanent running job and held resources.

**Reproduction steps:** Fake child writes beyond stderr capacity before stdin reading; enforce external timeout in isolated test.

**Evidence:** Static pipe ordering. Short encode passed; saturation/soak not executed.

- `src/echoforge/stages/renderer/exporter.py:263` — `proc=subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)`
- `src/echoforge/stages/renderer/exporter.py:283` — `proc.stdin.write(frame.tobytes())`
- `src/echoforge/stages/renderer/exporter.py:286` — `proc.stdin.close(); err=proc.stderr.read().decode("utf-8",errors="ignore") if proc.stderr else ""; code=proc.wait()`

**Recommended fix:** Drain concurrently or redirect stderr; timeouts and reliable terminate/reap.

**Regression tests:** Large stderr, early exit, slow encode, cancellation and long render.

**Dependencies:** Exporter process management and job recovery.

### STATE-018 — Running jobs permanently block after restart

**Issue ID:** STATE-018  
**Severity:** High  
**Confidence:** Confirmed  
**Affected files:** `src/echoforge/stages/renderer/render_jobs.py:17`, `src/echoforge/stages/renderer/render_jobs.py:47`, `scripts/render_upload_project.py:75`

**Intended behavior:** Reconcile interrupted worker ownership and allow safe retry.

**Actual behavior:** Restored active records have no worker; guard returns already_running. Script crash can leave ownerless lock.

**Root cause:** Flags/locks lack leases and boot reconciliation.

**Failure scenario:** Server stops while rendering; next boot cannot restart same project.

**Impact:** Manual state intervention required; daemon work lost.

**Reproduction steps:** Load temp running jobs record without a worker and call start with mocked Thread.

**Evidence:** test_stale_job_restart_recoverable failed: already_running=True.

- `src/echoforge/stages/renderer/render_jobs.py:17` — `_JOBS = json.loads(_JOBS_FILE.read_text(encoding="utf-8"))`
- `src/echoforge/stages/renderer/render_jobs.py:47` — `if same_project and active:`
- `scripts/render_upload_project.py:75` — `if lock_file.exists() and not args.force:`

**Recommended fix:** Durable leases/PID/heartbeat; boot reconciliation, interrupted status and owner-aware atomic locks.

**Regression tests:** Shutdown in render/upload, orphan lock, live owner, two servers and malformed ledger.

**Dependencies:** Jobs, subprocess workers, status endpoints and upload idempotency.

### INTEGRATION-019 — Render modal discards approved metadata and schedule

**Issue ID:** INTEGRATION-019  
**Severity:** High  
**Confidence:** Confirmed  
**Affected files:** `apps/webeditor/index.html:633`, `scripts/open_webeditor.py:120`, `scripts/open_webeditor.py:393`, `scripts/render_upload_project.py:67`

**Intended behavior:** Final action forwards reviewed metadata, visibility and aware schedule to one worker.

**Actual behavior:** Capture listener intercepts final buttons, omits metadata and uses nonmatching visibility selector. --request is ignored; --schedule-time differs from supported --schedule-at.

**Root cause:** Three appended protocols and permissive CLI parsing hide mismatches.

**Failure scenario:** Choose Public/custom title; action sends Private/no title. Alternate request-file route renders without requested upload.

**Impact:** User approval ignored; upload skipped or schedule lost.

**Reproduction steps:** Intercepted Playwright fixture and two mocked CLI-contract tests.

**Evidence:** Browser captured /api/render-upload-start with upload=true, visibility=private, schedule_time empty. Title/visibility/save checks failed; --request and schedule tests also failed.

- `apps/webeditor/index.html:633` — `const visibilityEl = document.querySelector("[name='visibility'], #visibility, select[data-role='visibility']");`
- `scripts/open_webeditor.py:120` — `cmd += ["--schedule-time", schedule_time]`
- `scripts/open_webeditor.py:393` — `"--request",`
- `scripts/render_upload_project.py:67` — `args, unknown = ap.parse_known_args()`

**Recommended fix:** One schema/route/listener; strict parser; forward approved fields and common terminal status.

**Regression tests:** All visibility modes, edited metadata, render-only, schedule, invalid args and terminal progress.

**Dependencies:** HTML, server routes, script worker and YouTube script.

### UPLOAD-020 — Primary upload bypasses duplicate protection

**Issue ID:** UPLOAD-020  
**Severity:** High  
**Confidence:** Confirmed  
**Affected files:** `scripts/run_router.py:65`, `scripts/youtube_upload_project.py:94`, `src/echoforge/stages/tubeharbor/upload_db.py:12`, `src/echoforge/stages/tubeharbor/youtube_uploader.py:59`

**Intended behavior:** Repeat/resume does not create another remote logical upload.

**Actual behavior:** Script never uses module ledger; module guard fails open on corrupt JSON and has check/upload/crash races.

**Root cause:** Independent upload/state implementations and late nontransactional recording.

**Failure scenario:** Repeat successful root upload or restart after remote success/local-record failure.

**Impact:** Duplicate videos, quota and ambiguous history.

**Reproduction steps:** Seed successful fixture report; mock client/media; call script upload twice.

**Evidence:** test_uploaded_script_guard failed: insert called twice. No remote requests.

- `scripts/run_router.py:65` — `return run([PY, "scripts/youtube_upload_project.py", *rest])`
- `scripts/youtube_upload_project.py:94` — `request = yt.videos().insert(part="snippet,status", body=body, media_body=media)`
- `src/echoforge/stages/tubeharbor/upload_db.py:12` — `except Exception:`
- `src/echoforge/stages/tubeharbor/youtube_uploader.py:59` — `if upload_db.is_uploaded(project): return {"ok":False,"stage":"upload","reason":f"Project {project.name} is already uploaded."}`

**Recommended fix:** One uploader and durable logical-upload ledger with claims/remote-ID reconciliation; fail closed and validate ID.

**Regression tests:** Repeat, two workers, corrupt ledger, empty ID, crash after insert, thumbnail failure and explicit replacement.

**Dependencies:** Router, both uploaders, jobs, status and project state.

### STATE-021 — State writers destroy or contradict workflow history

**Issue ID:** STATE-021  
**Severity:** High  
**Confidence:** Confirmed  
**Affected files:** `apps/webeditor_legacy/backend/main.py:634`, `scripts/mark_project_uploaded.py:117`, `src/echoforge/core/project_builder.py:251`

**Intended behavior:** Preserve song/source identity and coherent stage history during editing/upload/resume.

**Actual behavior:** Legacy save rewrites state without song_id/stages. Mark-uploaded overwrites source youtube_url and adds uploaded=True but canonical stages remain pending. Reuse downgrades song to selected.

**Root cause:** Multiple unversioned writers and overloaded URL/status fields.

**Failure scenario:** Legacy save staged project; or mark uploaded then force collection; source/history is lost or the published lyric video becomes source.

**Impact:** Wrong source downloads and unreconcilable completion state.

**Reproduction steps:** Temp state with identity/stages: call legacy writer and compare. Exercise mark logic only against temp DB.

**Evidence:** Destructive writes verified. Real read-only snapshots show uploaded with renderer/tubeharbor pending. Live remote success was not independently verified.

- `apps/webeditor_legacy/backend/main.py:634` — `def write_project_state(project_dir: Path, project: dict[str, Any]) -> None:`
- `scripts/mark_project_uploaded.py:117` — `state["youtube_url"] = url`
- `src/echoforge/core/project_builder.py:251` — `mark_song_status(song_id, "selected", project_dir=str(project_dir), note="Existing project reused")`

**Recommended fix:** Versioned state service with partial updates, separate source/output URLs and guarded monotonic transitions.

**Regression tests:** Legacy preserves fields, upload reconciles stores, completed reuse and post-upload recollection.

**Dependencies:** Builder, SQLite, collector, editors, uploader and status.

### FLOW-023 — Workflow continues failures and chooses a previous project

**Issue ID:** FLOW-023  
**Severity:** High  
**Confidence:** Confirmed  
**Affected files:** `scripts/workflow_all.py:89`, `scripts/workflow_all.py:106`, `scripts/render_project.py:7`, `src/echoforge/stages/renderer/exporter.py:299`, `apps/webeditor/app.js:642`

**Intended behavior:** Stop dependent work on failure; process explicit project; preserve manual edits on resume.

**Actual behavior:** ok=False may exit zero; no path falls back to unrelated latest project; resume force-prepares editor. Renderer prints failure but exits zero, allowing stale-output upload. Browser saveProject catches failure and resolves, so downstream render also continues a failed save.

**Root cause:** No shared structured result/exit contract plus unrelated fallback.

**Failure scenario:** No new songs: init-next fails but latest uploaded project gets recollected. Render failure can be treated as complete.

**Impact:** Wrong project, lost timeline or stale video published.

**Reproduction steps:** Mock init-next failure and latest fixture, capture subsequent commands.

**Evidence:** test_no_song_does_not_resume_other_project failed: collect occurred for old project. Exit/force defects traced statically. The fully mocked browser additionally started render after a 500 save response.

- `scripts/workflow_all.py:89` — `project = parse_project_dir(out) or latest_project()`
- `scripts/workflow_all.py:106` — `run([PY, "scripts/prepare_editor_project.py", "--project", project, "--force"])`
- `scripts/render_project.py:7` — `if __name__=="__main__": main()`
- `src/echoforge/stages/renderer/exporter.py:299` — `print(json.dumps(export_editor_project(a.project,a.output,a.fps,a.crf,lambda x: print(x.get("message",x),flush=True)),indent=2,ensure_ascii=False))`
- `apps/webeditor/app.js:642` — `setStatus(\`Save failed: ${err.message}\`);`

**Recommended fix:** Nonzero failures, explicit result/project validation, no latest fallback, optional rebuild and output hash/validation before upload.

**Regression tests:** No songs, failed stages, manual edited resume, stale MP4 and normal editor shutdown.

**Dependencies:** CLI, workflow, builder, renderer and worker script.

### SEC-024 — Root media route exposes credential files

**Issue ID:** SEC-024  
**Severity:** High  
**Confidence:** Confirmed  
**Affected files:** `scripts/open_webeditor.py:488`, `scripts/open_webeditor.py:490`

**Intended behavior:** Serve only approved public assets.

**Actual behavior:** Containment allows any repository file, including .env/.secrets, with no authentication.

**Root cause:** Containment is mistaken for authorization.

**Failure scenario:** Reachable client requests /root/.secrets/youtube_token.json.

**Impact:** OAuth/API credential disclosure; public bind increases risk.

**Reproduction steps:** Patch root to temp .secrets/dummy.txt; handler spy on do_GET.

**Evidence:** test_root_route_denies_secret_fixture failed: dummy secret passed to send_file. No real secret served/read.

- `scripts/open_webeditor.py:488` — `if path.startswith("/root/"):`
- `scripts/open_webeditor.py:490` — `return self.send_file(safe_join(ROOT_DIR, path[len("/root/") :]))`

**Recommended fix:** Remove broad root route; explicit public allowlist, hidden-path denial, loopback plus authenticated/origin-checked writes.

**Regression tests:** Secrets/config/git denial, allowed fonts, encoded traversal and symlinks.

**Dependencies:** Server, asset URLs and credential storage.

### SEC-025 — Untrusted paths and unbounded renders lack constraints

**Issue ID:** SEC-025  
**Severity:** High  
**Confidence:** High confidence  
**Affected files:** `src/echoforge/stages/renderer/exporter.py:38`, `src/echoforge/stages/renderer/exporter.py:248`, `src/echoforge/stages/renderer/webeditor_server.py:190`, `scripts/open_webeditor.py:528`

**Intended behavior:** Editor inputs only access approved roots and bounded resources.

**Actual behavior:** Schema-only save accepts unchecked paths/numbers; exporter accepts absolute assets/output. Older asset route may serve supplied absolute files.

**Root cause:** No common request/asset/output validator or trust boundary.

**Failure scenario:** Reachable malicious/local client submits arbitrary output, private asset or huge canvas/FPS/duration.

**Impact:** Disclosure, unintended overwrite or CPU/disk exhaustion; default loopback limits reach.

**Reproduction steps:** Dummy paths and fake exporters in isolation; do not attack actual files or exhaust resources.

**Evidence:** Static acceptance established; remote exploit, cross-origin exploit and exhaustion not tested.

- `src/echoforge/stages/renderer/exporter.py:38` — `if p.is_absolute(): return p`
- `src/echoforge/stages/renderer/exporter.py:248` — `out=Path(output) if output else project_dir/"renders/final_video.mp4"`
- `src/echoforge/stages/renderer/webeditor_server.py:190` — `def asset(self, name: str) -> Path | None:`
- `scripts/open_webeditor.py:528` — `if data.get("schema") != "echoforge.webeditor.v2":`

**Recommended fix:** Allowlist/resolved roots, bounded finite numeric values, authenticated writes/origin policy and request limits.

**Regression tests:** Traversal/absolute/symlink paths, out-of-root output, NaN/infinity/huge dimensions and permitted render.

**Dependencies:** Servers, exporter and worker options.

### INTEGRATION-026 — Studio has no compatible backend in repository

**Issue ID:** INTEGRATION-026  
**Severity:** High  
**Confidence:** Confirmed  
**Affected files:** `apps/web-studio/frontend/src/api.ts:43`, `apps/web-studio/frontend/src/api.ts:59`, `apps/webeditor_legacy/backend/main.py:1274`

**Intended behavior:** Shipped Studio has matching dashboard/projects/actions/drafts/jobs/settings API.

**Actual behavior:** Endpoints absent in both included services; legacy projects returns wrapper instead of array; new backend scaffolds empty.

**Root cause:** Frontend without service contract or launch route.

**Failure scenario:** Serve Studio against included server; startup Promise.all fails.

**Impact:** Studio feature set is inoperable with included services.

**Reproduction steps:** Compare every api.ts endpoint against both route inventories and empty scaffolds.

**Evidence:** Full source inventories inspected; no compatible service discovered. External backend not supplied.

- `apps/web-studio/frontend/src/api.ts:43` — `return request<DashboardPayload>("/api/dashboard");`
- `apps/web-studio/frontend/src/api.ts:59` — `return request<LogItem[]>("/api/logs?limit=120");`
- `apps/webeditor_legacy/backend/main.py:1274` — `@app.get("/api/projects")`

**Recommended fix:** Implement canonical API and launch flow or clearly exclude prototype from production.

**Regression tests:** Every client endpoint, startup, lifecycle, drafts, readiness and jobs.

**Dependencies:** Studio, build/launch, state contracts and empty backend.

### TIME-041 — Past or timezone-naive publish times are forwarded unchecked

**Issue ID:** TIME-041  
**Severity:** High  
**Confidence:** High confidence  
**Affected files:** `scripts/youtube_upload_project.py:80`, `src/echoforge/stages/tubeharbor/youtube_uploader.py:66`

**Intended behavior:** Scheduled upload should validate an unambiguous future publication instant or require explicit immediate-public intent.

**Actual behavior:** Uploaders forward arbitrary strings without parsing zone or checking future time; script only checks presence for schedule.

**Root cause:** Scheduling validation delegated to external API without enforcing user-level future-schedule semantics.

**Failure scenario:** A saved schedule becomes stale during downtime, then upload is retried; an accepted past publishAt causes immediate publication.

**Impact:** Potential unexpectedly public video instead of deferred release. Live publication was not exercised.

**Reproduction steps:** Mock uploader with a past ISO timestamp and inspect status body; never publish a real test video.

**Evidence:** Source forwarding is verified. Official YouTube status.publishAt documentation says accepted past times publish immediately; downstream outcome is an inference from that contract, not a live test. [Official YouTube video status.publishAt contract](https://developers.google.com/youtube/v3/docs/videos#status.publishAt).

- `scripts/youtube_upload_project.py:80` — `status["publishAt"] = args.schedule_at`
- `src/echoforge/stages/tubeharbor/youtube_uploader.py:66` — `if pub: body["status"]["publishAt"]=pub`

**Recommended fix:** Parse aware ISO instants, compare to one UTC clock plus scheduling margin, reject/confirm stale schedules and normalize zone before request.

**Regression tests:** Past, now, future, missing offset, invalid string, delayed retry and DST ambiguous/nonexistent local times.

**Dependencies:** Both uploaders, editor schedule forms, legacy schedule JSON and retry recovery.


## 6. Medium-Severity Issues


### DATA-003 — Selection retains obsolete chart ranks

**Issue ID:** DATA-003  
**Severity:** Medium  
**Confidence:** Requires specification clarification  
**Affected files:** `src/echoforge/stages/songscout/database.py:295`, `src/echoforge/stages/songscout/database.py:157`

**Intended behavior:** Current-chart selection should use current membership; a lifetime backlog needs an explicit historical ordering policy.

**Actual behavior:** Absent songs keep old rank/new status and can outrank fresh entries.

**Root cause:** Upsert accumulates history; selection has no snapshot-membership filter.

**Failure scenario:** Old rank 1 disappears; new snapshot has Fresh rank 2; Old is selected.

**Impact:** Off-chart output if current-chart intent; backlog semantics are unspecified.

**Reproduction steps:** Temp DB: upsert Old, then Fresh, select next.

**Evidence:** test_old_chart_not_selected failed: old != fresh. Selection behavior confirmed, requirement ambiguous.

- `src/echoforge/stages/songscout/database.py:295` — `WHERE status IN ({placeholders})`
- `src/echoforge/stages/songscout/database.py:157` — `def upsert_songs(songs: list[dict[str, Any]]) -> dict[str, int]:`

**Recommended fix:** Store cycle/snapshot membership independently of durable workflow status and select by agreed policy.

**Regression tests:** Removed song, re-entry, rank changes, used exclusion and intentional backlog.

**Dependencies:** Refresh, selector and project allocation.

### CONFIG-006 — Environment loading and credential names disagree

**Issue ID:** CONFIG-006  
**Severity:** Medium  
**Confidence:** Confirmed  
**Affected files:** `src/echoforge/core/config.py:9`, `src/echoforge/stages/musevault/genius_lyrics.py:24`, `src/echoforge/stages/tubeharbor/youtube_uploader.py:15`, `scripts/youtube_upload_project.py:41`

**Intended behavior:** Documented .env should configure startup and common upload paths.

**Actual behavior:** Settings freeze import-time environment; .env is loaded late only by Genius. *_PATH documentation differs from *_FILE module lookup and hardcoded script secrets.

**Root cause:** No central early configuration service.

**Failure scenario:** Config only in .env is ignored by early chart/timezone decisions or uploader path discovery.

**Impact:** Wrong settings and avoidable authentication failures.

**Reproduction steps:** Compare import-time settings before Genius loading; compare credential resolvers to .env.example without secrets.

**Evidence:** Source evaluation/resolvers verified; actual .env key names reviewed with values redacted.

- `src/echoforge/core/config.py:9` — `class Settings:`
- `src/echoforge/stages/musevault/genius_lyrics.py:24` — `def load_env(project_dir: Path) -> None:`
- `src/echoforge/stages/tubeharbor/youtube_uploader.py:15` — `r=root(project_dir); sec=r/".secrets"; env=os.environ.get("YOUTUBE_CLIENT_SECRET_FILE"); cand=[]`
- `scripts/youtube_upload_project.py:41` — `client_secret = secrets / "youtube_client_secret.json"`

**Recommended fix:** Load/validate settings before stages import; share one credential/timezone contract across entry points.

**Regression tests:** .env-only, environment precedence, invalid integers, alternate secret directory and timezone.

**Dependencies:** Startup, chart policy, Genius and both uploaders.

### MEDIA-008 — Force-normalize uses the same input and output

**Issue ID:** MEDIA-008  
**Severity:** Medium  
**Confidence:** Confirmed  
**Affected files:** `src/echoforge/stages/musevault/audio_normalizer.py:71`, `src/echoforge/stages/musevault/audio_normalizer.py:60`

**Intended behavior:** Force safely regenerates normalized audio.

**Actual behavior:** Existing m4a source is also the FFmpeg destination.

**Root cause:** Target prioritized as source; force bypasses self-input guard.

**Failure scenario:** User runs normalize --force after normal completion.

**Impact:** FFmpeg refuses; recovery option fails.

**Reproduction steps:** Capture mocked subprocess command with existing m4a and force=True.

**Evidence:** test_force_audio_distinct_paths failed: paths identical.

- `src/echoforge/stages/musevault/audio_normalizer.py:71` — `"source": str(source),`
- `src/echoforge/stages/musevault/audio_normalizer.py:60` — `"target": str(target),`

**Recommended fix:** Use distinct temporary output and replace after validation.

**Regression tests:** Existing m4a, other formats, failed conversion and force retry.

**Dependencies:** Normalization script and forced MuseVault/VerseLock paths.

### SYNC-011 — Invalid existing LRC prevents automatic fallback

**Issue ID:** SYNC-011  
**Severity:** Medium  
**Confidence:** Confirmed  
**Affected files:** `src/echoforge/stages/verselock/sync_runner.py:235`, `src/echoforge/stages/verselock/synced_reuse.py:107`

**Intended behavior:** Auto mode should fall back when source LRC is unusable.

**Actual behavior:** Existence routes immediately to reuse; invalid result returns without Whisper.

**Root cause:** Dispatcher checks presence rather than successful parsing.

**Failure scenario:** Malformed online LRC remains on disk; every auto attempt fails despite valid audio/plain lyrics.

**Impact:** Recovery requires manual file intervention or explicit mode.

**Reproduction steps:** Seed metadata-only LRC; mock inference and assert fallback invoked.

**Evidence:** Static branch trace; no live inference executed.

- `src/echoforge/stages/verselock/sync_runner.py:235` — `if existing_lrc.exists() and not force_fallback:`
- `src/echoforge/stages/verselock/synced_reuse.py:107` — `if not lines:`

**Recommended fix:** Continue fallback after invalid reuse and preserve rejection reason.

**Regression tests:** Empty/invalid/valid/missing LRC, missing audio and forced mode.

**Dependencies:** Online fetcher, reuse, sync runner and Whisper.

### SYNC-012 — Lyric JSON and LRC parser contracts diverge

**Issue ID:** SYNC-012  
**Severity:** Medium  
**Confidence:** Confirmed  
**Affected files:** `src/echoforge/stages/renderer/editor_project_v2.py:83`, `src/echoforge/stages/verselock/lrc_parser.py:15`, `src/echoforge/stages/renderer/editor_project_v2.py:52`

**Intended behavior:** Producers and editors share canonical timing schema/parser.

**Actual behavior:** Final start_seconds/end_seconds are unrecognized by V2; multiple timestamp/offset handling differs among readers.

**Root cause:** Parallel custom parsers and incomplete aliases.

**Failure scenario:** Only valid final JSON exists; editor gets no lines. Multi-timestamp LRC differs by route.

**Impact:** Missing or inconsistent lyric timelines; usual LRC fallback masks mismatch.

**Reproduction steps:** normalize_line with text and start_seconds=1,end_seconds=2; compare repeated-timestamp/offset parsing.

**Evidence:** test_v2_reads_canonical_json failed: None. Other parser cases inspected statically.

- `src/echoforge/stages/renderer/editor_project_v2.py:83` — `start = item.get("start", item.get("start_time", item.get("time", item.get("timestamp"))))`
- `src/echoforge/stages/verselock/lrc_parser.py:15` — `start_seconds: float`
- `src/echoforge/stages/renderer/editor_project_v2.py:52` — `LRC_RE = re.compile(r"\[(\d{1,2}:\d{2}(?:\.\d{1,3})?)\](.*)")`

**Recommended fix:** Use common canonical parser/model, support real producer keys and define offset/blank-line handling.

**Regression tests:** JSON-only, repeats, offsets, unordered lines, blank timed intervals and invalid seconds.

**Dependencies:** Serializers, MuseVault parser, both builders and legacy discovery.

### RENDER-015 — Missing clips produce invalid FFmpeg input indices

**Issue ID:** RENDER-015  
**Severity:** Medium  
**Confidence:** Confirmed  
**Affected files:** `src/echoforge/stages/renderer/exporter.py:226`, `src/echoforge/stages/renderer/exporter.py:228`, `src/echoforge/stages/renderer/exporter.py:230`

**Intended behavior:** Valid remaining inputs map to actual FFmpeg indexes.

**Actual behavior:** Missing first source is skipped; only input 0 exists but filter uses [1:a].

**Root cause:** Original clip index survives compacted input list.

**Failure scenario:** Two clips: missing first, valid second.

**Impact:** Audio timeline fails unnecessarily.

**Reproduction steps:** Capture command using missing/good temp clip sources.

**Evidence:** test_missing_audio_filter_indices failed: [1:a] with one -i.

- `src/echoforge/stages/renderer/exporter.py:226` — `for idx,c in enumerate(ac):`
- `src/echoforge/stages/renderer/exporter.py:228` — `if not p or not p.exists(): continue`
- `src/echoforge/stages/renderer/exporter.py:230` — `parts.append(f"[{idx}:a]atrim=start={ss:.3f}:end={ss+dd:.3f},asetpts=PTS-STARTPTS,adelay={de}|{de}[{lab}]")`

**Recommended fix:** Reject missing sources or index by actual appended input count.

**Regression tests:** First/middle/last/all missing; fallback and overlap.

**Dependencies:** Source resolver, mixer and render errors.

### STATE-022 — Failed upload report is displayed as uploaded

**Issue ID:** STATE-022  
**Severity:** Medium  
**Confidence:** Confirmed  
**Affected files:** `scripts/project_status.py:67`, `scripts/youtube_upload_project.py:112`

**Intended behavior:** Uploaded requires accepted success and valid remote identity.

**Actual behavior:** Any nonempty report including ok=False makes uploaded=True.

**Root cause:** Existence substitutes for semantic success.

**Failure scenario:** Upload error writes failure report; status displays a success check.

**Impact:** User trusts nonexistent publication or stops retrying.

**Reproduction steps:** Temp report {ok:false,error:fixture}; call status.

**Evidence:** test_failed_upload_not_uploaded failed: True.

- `scripts/project_status.py:67` — `"uploaded": checks["youtube_upload_report"] or str(state.get("status", "")).lower() == "uploaded",`
- `scripts/youtube_upload_project.py:112` — `thumb_result = {"ok": False, "error": str(exc)}`

**Recommended fix:** Check ok is True, valid ID and consistent ledger; separate failure state.

**Regression tests:** Failed/corrupt report, success without ID, real success and manual mark policy.

**Dependencies:** Uploader errors, marking and status.

### UI-027 — Studio async responses can lose or misroute edits

**Issue ID:** UI-027  
**Severity:** Medium  
**Confidence:** High confidence  
**Affected files:** `apps/web-studio/frontend/src/editors/LyricsEditor.tsx:178`, `apps/web-studio/frontend/src/editors/LyricsEditor.tsx:35`, `apps/web-studio/frontend/src/editors/SyncEditor.tsx:245`, `apps/web-studio/frontend/src/views/UploadManagerView.tsx:27`

**Intended behavior:** Apply responses only to originating project/revision and preserve newer edits.

**Actual behavior:** Save replaces arrays/clears dirty while typing remains enabled; project switch retains old payload until next load but actions use new ID.

**Root cause:** No response ownership/revision guard or complete edit lock.

**Failure scenario:** Type B while autosave A pending; response restores A. Switch project then save stale visible data.

**Impact:** Lost edits or cross-project writes if compatible backend is deployed.

**Reproduction steps:** Mounted component with controlled delayed promises, edit and switch before responses.

**Evidence:** Source state/effect analysis; no mounted delayed-response React test. Missing backend makes current exposure conditional.

- `apps/web-studio/frontend/src/editors/LyricsEditor.tsx:178` — `const next = await saveLyrics(project.id, lines, true);`
- `apps/web-studio/frontend/src/editors/LyricsEditor.tsx:35` — `setLines(next.lines);`
- `apps/web-studio/frontend/src/editors/SyncEditor.tsx:245` — `const next = normalizePayload(await saveTimestamps(project.id, segments, true));`
- `apps/web-studio/frontend/src/views/UploadManagerView.tsx:27` — `useEffect(() => {`

**Recommended fix:** Project-keyed revisioned editor state, reset/disable before load, ignore stale responses and preserve newer dirty revision.

**Regression tests:** Typing during save, switch mid-save/load, failed load, A-B-A and approve/draft races.

**Dependencies:** Studio selection, lyric/sync/template/upload forms and future API versions.

### BUILD-028 — Declared Python minimum cannot parse metadata generator

**Issue ID:** BUILD-028  
**Severity:** Medium  
**Confidence:** Confirmed  
**Affected files:** `pyproject.toml:5`, `src/echoforge/stages/tubeharbor/metadata_generator.py:374`

**Intended behavior:** Every declared Python version imports application.

**Actual behavior:** Backslash f-string expression requires 3.12; package advertises >=3.10.

**Root cause:** Language feature exceeds runtime declaration.

**Failure scenario:** Python 3.10/3.11 parses metadata module.

**Impact:** Startup/metadata SyntaxError on supported runtime.

**Reproduction steps:** Ruff project target, or actual older Python import.

**Evidence:** Ruff invalid-syntax line 374; 3.13 AST/import succeeds. Older interpreter unavailable. Official Python 3.12 docs confirm restriction change. [Official Python 3.12 f-string changes](https://docs.python.org/3/whatsnew/3.12.html#pep-701-syntactic-formalization-of-f-strings).

- `pyproject.toml:5` — `requires-python = ">=3.10"`
- `src/echoforge/stages/tubeharbor/metadata_generator.py:374` — `f"{'\n'.join(search_lines)}\n\n"`

**Recommended fix:** Precompute joined text or consistently raise/document minimum.

**Regression tests:** Supported-version import/CLI matrix and multiline metadata.

**Dependencies:** Packaging, CLI/import chain and metadata.

### DB-029 — SQLite transaction contexts do not close connections

**Issue ID:** DB-029  
**Severity:** Medium  
**Confidence:** Confirmed  
**Affected files:** `src/echoforge/stages/songscout/database.py:122`, `src/echoforge/stages/songscout/database.py:53`

**Intended behavior:** Close every connection promptly.

**Actual behavior:** with connection commits/rolls back but leaves it open, relying on GC.

**Root cause:** Transaction context confused with resource-lifetime context.

**Failure scenario:** Repeated operations or held tracebacks retain database handles.

**Impact:** Resource accumulation and Windows maintenance/cleanup problems.

**Reproduction steps:** Temp connection: SELECT inside with then execute after exit.

**Evidence:** test_sqlite_context_closes_connection failed. Earlier fixture teardown got WinError 32; corrected harness explicitly closed its own connections.

- `src/echoforge/stages/songscout/database.py:122` — `with connect() as conn:`
- `src/echoforge/stages/songscout/database.py:53` — `conn = sqlite3.connect(path)`

**Recommended fix:** Explicit finally close/contextlib.closing plus transaction scope.

**Regression tests:** Repeated reads/writes, rollback exception, explicit closure and Windows cleanup.

**Dependencies:** All DB callers and long-lived services.

### LYRICS-030 — Search normalization removes x within words

**Issue ID:** LYRICS-030  
**Severity:** Medium  
**Confidence:** Confirmed  
**Affected files:** `src/echoforge/stages/musevault/metadata_review.py:62`

**Intended behavior:** Preserve letters; split only collaborator separators.

**Actual behavior:** Taxi becomes Ta i.

**Root cause:** Character class matches every lowercase x.

**Failure scenario:** Title/artist contains x; wrong query goes to lyrics services.

**Impact:** Missing/wrong lyrics.

**Reproduction steps:** search_text("Taxi").

**Evidence:** test_search_preserves_x failed: Ta i.

- `src/echoforge/stages/musevault/metadata_review.py:62` — `text = re.sub(r"[&×x,]", " ", text)`

**Recommended fix:** Use separator boundaries and preserve lexical letters.

**Regression tests:** Taxi, next, x collaborator, X and Unicode separators.

**Dependencies:** Review metadata, LRCLIB and Genius.

### CHART-031 — Numeric titles are treated as metrics

**Issue ID:** CHART-031  
**Severity:** Medium  
**Confidence:** Confirmed  
**Affected files:** `src/echoforge/stages/songscout/cleaner.py:80`, `src/echoforge/stages/songscout/cleaner.py:102`

**Intended behavior:** Keep numeric song titles when semantic hints missing.

**Actual behavior:** 7 is stripped as rank/views; remaining artist can be misassigned or row lost.

**Root cause:** Context-free metric filtering.

**Failure scenario:** DOM hints missing for a numeric title.

**Impact:** Silent chart omission/incorrect identity.

**Reproduction steps:** title_artist_from_lines([1,7,Singer Name,100 views]) using strings.

**Evidence:** test_numeric_title failed; fixture performer is not reserved label Artist.

- `src/echoforge/stages/songscout/cleaner.py:80` — `return low in LABEL_ONLY_VALUES or is_rank_line(low) or looks_like_views(low) or looks_like_date(low)`
- `src/echoforge/stages/songscout/cleaner.py:102` — `if is_noise_line(line) or is_metric_or_label_line(line):`

**Recommended fix:** Semantic field extraction and contextual rank/view positions.

**Regression tests:** 7, 2025, numeric artist, merged/missing hints and ordinary song.

**Dependencies:** Scraper, cleaner, refresh gate and identity.

### UPLOAD-032 — Privacy alias is ignored by default visibility

**Issue ID:** UPLOAD-032  
**Severity:** Medium  
**Confidence:** Confirmed  
**Affected files:** `scripts/youtube_upload_project.py:72`, `scripts/youtube_upload_project.py:136`

**Intended behavior:** Explicit --privacy applies when --visibility absent.

**Actual behavior:** Always-present private default wins over alias.

**Root cause:** Default participates as if explicitly chosen.

**Failure scenario:** Use --privacy public only.

**Impact:** Video visibility differs from command; schedule alias ignored.

**Reproduction steps:** Parse args and mock API to inspect status.

**Evidence:** Static default/precedence trace; alias-specific API test not executed.

- `scripts/youtube_upload_project.py:72` — `visibility = args.visibility or args.privacy or "private"`
- `scripts/youtube_upload_project.py:136` — `ap.add_argument("--visibility", choices=["private", "public", "unlisted", "schedule"], default="private")`

**Recommended fix:** Default visibility None, resolve once and reject conflicts.

**Regression tests:** Alias-only, visibility-only, conflict, schedule and default.

**Dependencies:** Wrappers and upload CLI.

### TIME-033 — Refresh completion uses host calendar zone

**Issue ID:** TIME-033  
**Severity:** Medium  
**Confidence:** Confirmed  
**Affected files:** `src/echoforge/stages/songscout/database.py:362`, `src/echoforge/stages/songscout/policy.py:14`

**Intended behavior:** Eligibility/completion share configured timezone/cycle.

**Actual behavior:** Policy uses ECHOFORGE_TIMEZONE; recording uses host-local date.

**Root cause:** Independent date computation.

**Failure scenario:** Kolkata Friday 00:10 on UTC host Thursday 18:40 stores Thursday; next Friday run eligible again.

**Impact:** Duplicate refresh around midnight.

**Reproduction steps:** Freeze both clocks across this boundary with temp DB.

**Evidence:** Two clock sources verified; frozen recorder cross-zone test not executed.

- `src/echoforge/stages/songscout/database.py:362` — `today = datetime.now().astimezone().date().isoformat()`
- `src/echoforge/stages/songscout/policy.py:14` — `tz_name = os.getenv("ECHOFORGE_TIMEZONE", "Asia/Kolkata")`

**Recommended fix:** Persist cycle/date from policy decision and separate UTC event timestamp.

**Regression tests:** Host/config mismatch, DST zone, midnight, retry and tzdata absence.

**Dependencies:** Policy, recorder and refresh callers.

### UI-035 — First legacy Shift-click uses undeclared selection variable

**Issue ID:** UI-035  
**Severity:** Medium  
**Confidence:** Confirmed  
**Affected files:** `apps/webeditor_legacy/frontend/src/main.jsx:671`, `apps/webeditor_legacy/frontend/src/main.jsx:734`

**Intended behavior:** First Shift-click selects safely.

**Actual behavior:** Null anchor evaluates selectedClipId outside Timeline scope.

**Root cause:** Prop missing from caller/destructuring.

**Failure scenario:** Shift-click before normal selection.

**Impact:** ReferenceError aborts selection.

**Reproduction steps:** Mounted legacy fixture first Shift-click or lexical fallback check.

**Evidence:** Full component scope inspected; mounted test not run.

- `apps/webeditor_legacy/frontend/src/main.jsx:671` — `function Timeline({ project, currentTime, setCurrentTime, selectedClipIds, setSelectedClipId, setSelectedClipIds, updateProject, onAddLyric, snap, triggerDelete, triggerDuplicate }) {`
- `apps/webeditor_legacy/frontend/src/main.jsx:734` — `const anchorId = lastSelectedClipIdRef.current || selectedClipId;`

**Recommended fix:** Pass selection prop or derive defined fallback.

**Regression tests:** First Shift, normal-Shift, Ctrl, empty and locked.

**Dependencies:** Legacy Editor/Timeline contract.

### QA-037 — Automated regression test files are empty

**Issue ID:** QA-037  
**Severity:** Medium  
**Confidence:** Confirmed  
**Affected files:** `tests/test_workflow.py (empty; no line)`, `tests/test_musevault.py (empty; no line)`, `tests/test_songscout.py (empty; no line)`, `tests/test_verselock.py (empty; no line)`

**Intended behavior:** Business/recovery contracts protected by executable tests.

**Actual behavior:** Four test modules and initializer contain no assertions.

**Root cause:** Unimplemented test scaffolds; no checked-in CI found.

**Failure scenario:** Integration defect reaches release without a regression signal.

**Impact:** No automated reliability assurance.

**Reproduction steps:** python -B -m pytest -p no:cacheprovider tests -q.

**Evidence:** No tests ran; tool reported exit 1. Empty file has no line number; none is invented.

- `tests/test_workflow.py (empty; no line)` — `[empty file]`
- `tests/test_musevault.py (empty; no line)` — `[empty file]`
- `tests/test_songscout.py (empty; no line)` — `[empty file]`
- `tests/test_verselock.py (empty; no line)` — `[empty file]`

**Recommended fix:** After audit, add isolated contracts/regressions and runtime CI matrix.

**Regression tests:** Fixture/browser cases plus leases, crash recovery and service mocks.

**Dependencies:** Entire release/testing process.

### BUILD-038 — Package omits direct runtime dependency declaration

**Issue ID:** BUILD-038  
**Severity:** Medium  
**Confidence:** Confirmed  
**Affected files:** `pyproject.toml:1`, `requirements.txt:2`

**Intended behavior:** Distributable installs runtime imports with tested optional extras.

**Actual behavior:** No project.dependencies; separate requirements omit direct requests/Pillow and Windows timezone data.

**Root cause:** Dependence on manual/transitive/ambient installs.

**Failure scenario:** Fresh package-only install exposes CLI without import prerequisites.

**Impact:** Deployment startup failure; host success cannot prove clean compatibility.

**Reproduction steps:** Inspect metadata; clean disposable install/help test is recommended, not performed.

**Evidence:** Metadata verified; current 3.13 help passed. Host pip check reports torchvision 0.26.0 requires torch 2.11.0 but installed 2.10.0, an environment mismatch, not a universal install failure.

- `pyproject.toml:1` — `[project]`
- `requirements.txt:2` — `python-dotenv>=1.0.0`

**Recommended fix:** Declare direct core dependencies, tested optional inference extras and consistent setup.

**Regression tests:** Clean install/help, missing heavy engine, Windows zones and CPU inference imports.

**Dependencies:** Packaging, requirements, setup and eager imports.

### STATE-039 — JSON state writes are not crash-safe

**Issue ID:** STATE-039  
**Severity:** Medium  
**Confidence:** High confidence  
**Affected files:** `src/echoforge/stages/tubeharbor/upload_db.py:17`, `src/echoforge/stages/renderer/render_jobs.py:24`, `src/echoforge/core/project_builder.py:112`

**Intended behavior:** Preserve durable state and coordinated artifacts under interruption.

**Actual behavior:** Direct overwrite and multi-file updates; corrupt readers often return {}; ledger read-modify-write unguarded across processes.

**Root cause:** No atomic replace/transactional coordination/version.

**Failure scenario:** Crash during write or competing snapshots lose updates.

**Impact:** Lost history, reopened guard and inconsistent manifests.

**Reproduction steps:** Inject temp write truncation or coordinated fixture writers.

**Evidence:** Static write/failure paths; corrupt final reuse reproduced. Kill/lost-update stress not run.

- `src/echoforge/stages/tubeharbor/upload_db.py:17` — `DB_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")`
- `src/echoforge/stages/renderer/render_jobs.py:24` — `_JOBS_FILE.write_text(json.dumps(_JOBS, indent=2, ensure_ascii=False), encoding="utf-8")`
- `src/echoforge/core/project_builder.py:112` — `path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")`

**Recommended fix:** Atomic single-file replace; transactional coordinated state and explicit corruption handling.

**Regression tests:** Partial write, disk-full, permissions, concurrent readers/writers and paired promotion.

**Dependencies:** Project/sync/jobs/upload/editor state.

### SYNC-040 — Timing quality acceptance is underspecified

**Issue ID:** SYNC-040  
**Severity:** Medium  
**Confidence:** Requires specification clarification  
**Affected files:** `src/echoforge/stages/verselock/timestamp_transfer.py:352`, `src/echoforge/stages/verselock/timestamp_transfer.py:346`, `src/echoforge/stages/verselock/timestamp_transfer.py:348`

**Intended behavior:** Specify safe auto-promotion quality versus review, including multilingual tolerance.

**Actual behavior:** Gate measures skeleton count rather than similarity/coverage/coherent boundaries; low similarity explicitly allowed.

**Root cause:** No explicit quality contract; count alone cannot distinguish unrelated audio.

**Failure scenario:** Enough unrelated transcript segments are transferred proportionally.

**Impact:** Plausible but wrong timing may be accepted; quality tolerance ambiguous.

**Reproduction steps:** Eight unrelated segments and official lyrics; inspect acceptance/timing bounds in isolation.

**Evidence:** Count gate/note confirmed; wrong-song quality case not executed or claimed measured.

- `src/echoforge/stages/verselock/timestamp_transfer.py:352` — `ok = len(transferred) > 0 and len(whisper_lines) >= max(8, int(len(lyric_lines) * 0.55))`
- `src/echoforge/stages/verselock/timestamp_transfer.py:346` — `"average_text_similarity": avg_sim,`
- `src/echoforge/stages/verselock/timestamp_transfer.py:348` — `"note": "Text comes from lyrics.txt. Timestamps come from Whisper timing skeleton. Low text similarity is acceptable here when pronunciation differs.",`

**Recommended fix:** Define coverage/duration/monotonicity/review gates suitable for multilingual pronunciation.

**Regression tests:** Wrong versions, instrumental gaps, repeats, dense lyrics and monotonic nudging bounds.

**Dependencies:** Transfer, alternative aligner safety, sync runner and editor approval.


## 7. Low-Severity Issues


### RENDER-017 — Module entry executes before helper definitions

**Issue ID:** RENDER-017  
**Severity:** Low  
**Confidence:** Confirmed  
**Affected files:** `src/echoforge/stages/renderer/exporter.py:300`, `src/echoforge/stages/renderer/exporter.py:312`

**Intended behavior:** Module and imported wrapper entry points behave consistently.

**Actual behavior:** Module mode reaches softness helpers before their definitions; wrapper import mode works.

**Root cause:** __main__ invocation is in the middle of the module.

**Failure scenario:** python -m exporter with valid project reaches a NameError.

**Impact:** Alternate executable path fails.

**Reproduction steps:** Use isolated valid short fixture and module subprocess.

**Evidence:** Definition/execution ordering proves unresolved helper; specific module subprocess not run.

- `src/echoforge/stages/renderer/exporter.py:300` — `if __name__=="__main__": main()`
- `src/echoforge/stages/renderer/exporter.py:312` — `def render_softness_sigma() -> float:`

**Recommended fix:** Place entry invocation after all definitions.

**Regression tests:** Module-mode and wrapper-mode short render.

**Dependencies:** Exporter CLI and softness settings.

### START-034 — Launcher hardcodes obsolete checkout path

**Issue ID:** START-034  
**Severity:** Low  
**Confidence:** Confirmed  
**Affected files:** `start_echoforge.bat:3`

**Intended behavior:** Launch repository containing script.

**Actual behavior:** Hardcodes D:/Hello World/Automations/EchoForge, unlike root with 2. Automations.

**Root cause:** Committed machine-specific directory without cd failure guard.

**Failure scenario:** Old path missing or another checkout exists.

**Impact:** Failure or wrong code/data launched.

**Reproduction steps:** Compare batch path to verified root; do not execute launcher.

**Evidence:** Committed path inspected; portable root run.bat exists.

- `start_echoforge.bat:3` — `cd /d "D:\Hello World\Automations\EchoForge"`

**Recommended fix:** Resolve %~dp0 and check failure.

**Regression tests:** Moved path, spaces and two checkouts.

**Dependencies:** Windows startup/router.

### UI-036 — Legacy mute/solo controls do not affect audio

**Issue ID:** UI-036  
**Severity:** Low  
**Confidence:** Confirmed  
**Affected files:** `apps/webeditor_legacy/frontend/src/main.jsx:673`, `apps/webeditor_legacy/frontend/src/main.jsx:923`

**Intended behavior:** Mute/solo affects preview/export.

**Actual behavior:** State only changes button classes and never reaches Transport/project.

**Root cause:** Timeline-local cosmetic state.

**Failure scenario:** Press track M/S during playback.

**Impact:** Misleading audio approval.

**Reproduction steps:** Trace all variable usages; optional audible fixture.

**Evidence:** Only control usages in full source; audible test not run.

- `apps/webeditor_legacy/frontend/src/main.jsx:673` — `const [mutedTracks, setMutedTracks] = useState({});`
- `apps/webeditor_legacy/frontend/src/main.jsx:923` — `<button className={\`icon-btn ${soloTrack===track.id?'trackActive':''}\`} title="Solo track" onClick={() => setSoloTrack(s => s===track.id ? null : track.id)}>S</button>`

**Recommended fix:** Persist/consume common track mute/solo semantics.

**Regression tests:** Mute, solo, clear, reload and export.

**Dependencies:** Timeline, Transport and renderer.

## 8. File-by-File Inspection Findings

The register below includes every in-scope file, including empty scaffolds, binary assets and configuration. Issue IDs identify direct findings or explicitly labeled integration context. A file with no independently evidenced defect still received responsibility/input/error/state/consumer inspection; it is not declared bug-free. Empty files have no line numbers/callables. Tests Reviewed means the available tests/missing cases were examined, not that each file was dynamically exercised. Runtime tests that need service credentials or absent dependencies are blocked/limited in section 14.


| File | Responsibility Reviewed | Logic Reviewed | Integration Reviewed | Tests Reviewed | Result |
|---|---|---|---|---|---|
| `.env` | Partially Reviewed | Not Applicable | Partially Reviewed | Not Applicable | Keys only; values excluded; CONFIG-006 |
| `.env.example` | Reviewed | Reviewed | Reviewed | Not Applicable | No independently evidenced defect; relevant contracts/edge cases inspected |
| `.gitignore` | Reviewed | Reviewed | Reviewed | Not Applicable | No independently evidenced defect; relevant contracts/edge cases inspected |
| `Phase 1 Critical Fixes.pdf` | Reviewed | Not Applicable | Reviewed | Not Applicable | No independently evidenced defect; relevant contracts/edge cases inspected |
| `apps/web-studio/frontend/index.html` | Reviewed | Not Applicable | Reviewed | Not Applicable | No independently evidenced defect; relevant contracts/edge cases inspected |
| `apps/web-studio/frontend/package-lock.json` | Reviewed | Not Applicable | Reviewed | Not Applicable | No independently evidenced defect; relevant contracts/edge cases inspected |
| `apps/web-studio/frontend/package.json` | Reviewed | Not Applicable | Reviewed | Not Applicable | No independently evidenced defect; relevant contracts/edge cases inspected |
| `apps/web-studio/frontend/src/App.tsx` | Reviewed | Reviewed | Reviewed | Reviewed | No independently evidenced defect; relevant contracts/edge cases inspected |
| `apps/web-studio/frontend/src/api.ts` | Reviewed | Reviewed | Reviewed | Reviewed | INTEGRATION-026, INTEGRATION-026 |
| `apps/web-studio/frontend/src/editors/LyricsEditor.tsx` | Reviewed | Reviewed | Reviewed | Reviewed | UI-027, UI-027 |
| `apps/web-studio/frontend/src/editors/SyncEditor.tsx` | Reviewed | Reviewed | Reviewed | Reviewed | UI-027 |
| `apps/web-studio/frontend/src/main.tsx` | Reviewed | Reviewed | Reviewed | Reviewed | No independently evidenced defect; relevant contracts/edge cases inspected |
| `apps/web-studio/frontend/src/styles.css` | Reviewed | Not Applicable | Reviewed | Not Applicable | No independently evidenced defect; relevant contracts/edge cases inspected |
| `apps/web-studio/frontend/src/types.ts` | Reviewed | Reviewed | Reviewed | Reviewed | No independently evidenced defect; relevant contracts/edge cases inspected |
| `apps/web-studio/frontend/src/views/RenderQueueView.tsx` | Reviewed | Reviewed | Reviewed | Reviewed | No independently evidenced defect; relevant contracts/edge cases inspected |
| `apps/web-studio/frontend/src/views/SettingsView.tsx` | Reviewed | Reviewed | Reviewed | Reviewed | No independently evidenced defect; relevant contracts/edge cases inspected |
| `apps/web-studio/frontend/src/views/TemplatesView.tsx` | Reviewed | Reviewed | Reviewed | Reviewed | No independently evidenced defect; relevant contracts/edge cases inspected |
| `apps/web-studio/frontend/src/views/UploadManagerView.tsx` | Reviewed | Reviewed | Reviewed | Reviewed | UI-027 |
| `apps/web-studio/frontend/src/views/ViewSharedComponents.tsx` | Reviewed | Reviewed | Reviewed | Reviewed | No independently evidenced defect; relevant contracts/edge cases inspected |
| `apps/web-studio/frontend/tsconfig.json` | Reviewed | Not Applicable | Reviewed | Not Applicable | No independently evidenced defect; relevant contracts/edge cases inspected |
| `apps/webeditor/app.js` | Reviewed | Reviewed | Reviewed | Reviewed | FLOW-023 |
| `apps/webeditor/backend/app.py` | Reviewed | Not Applicable | Reviewed | Not Applicable | Verified zero bytes; unimplemented scaffold/placeholder |
| `apps/webeditor/backend/routes/__init__.py` | Reviewed | Not Applicable | Reviewed | Not Applicable | Verified zero bytes; unimplemented scaffold/placeholder |
| `apps/webeditor/backend/routes/editor.py` | Reviewed | Not Applicable | Reviewed | Not Applicable | Verified zero bytes; unimplemented scaffold/placeholder |
| `apps/webeditor/backend/routes/projects.py` | Reviewed | Not Applicable | Reviewed | Not Applicable | Verified zero bytes; unimplemented scaffold/placeholder |
| `apps/webeditor/backend/routes/render.py` | Reviewed | Not Applicable | Reviewed | Not Applicable | Verified zero bytes; unimplemented scaffold/placeholder |
| `apps/webeditor/backend/routes/upload.py` | Reviewed | Not Applicable | Reviewed | Not Applicable | Verified zero bytes; unimplemented scaffold/placeholder |
| `apps/webeditor/backend/schemas.py` | Reviewed | Not Applicable | Reviewed | Not Applicable | Verified zero bytes; unimplemented scaffold/placeholder |
| `apps/webeditor/backend/services/__init__.py` | Reviewed | Not Applicable | Reviewed | Not Applicable | Verified zero bytes; unimplemented scaffold/placeholder |
| `apps/webeditor/backend/services/media_service.py` | Reviewed | Not Applicable | Reviewed | Not Applicable | Verified zero bytes; unimplemented scaffold/placeholder |
| `apps/webeditor/backend/services/project_service.py` | Reviewed | Not Applicable | Reviewed | Not Applicable | Verified zero bytes; unimplemented scaffold/placeholder |
| `apps/webeditor/backend/services/render_service.py` | Reviewed | Not Applicable | Reviewed | Not Applicable | Verified zero bytes; unimplemented scaffold/placeholder |
| `apps/webeditor/backend/services/upload_service.py` | Reviewed | Not Applicable | Reviewed | Not Applicable | Verified zero bytes; unimplemented scaffold/placeholder |
| `apps/webeditor/frontend/index.html` | Reviewed | Not Applicable | Reviewed | Not Applicable | Verified zero bytes; unimplemented scaffold/placeholder |
| `apps/webeditor/frontend/package.json` | Reviewed | Not Applicable | Reviewed | Not Applicable | Verified zero bytes; unimplemented scaffold/placeholder |
| `apps/webeditor/frontend/src/App.jsx` | Reviewed | Not Applicable | Reviewed | Not Applicable | Verified zero bytes; unimplemented scaffold/placeholder |
| `apps/webeditor/frontend/src/api.js` | Reviewed | Not Applicable | Reviewed | Not Applicable | Verified zero bytes; unimplemented scaffold/placeholder |
| `apps/webeditor/frontend/src/components/Inspector.jsx` | Reviewed | Not Applicable | Reviewed | Not Applicable | Verified zero bytes; unimplemented scaffold/placeholder |
| `apps/webeditor/frontend/src/components/PreviewCanvas.jsx` | Reviewed | Not Applicable | Reviewed | Not Applicable | Verified zero bytes; unimplemented scaffold/placeholder |
| `apps/webeditor/frontend/src/components/ProjectList.jsx` | Reviewed | Not Applicable | Reviewed | Not Applicable | Verified zero bytes; unimplemented scaffold/placeholder |
| `apps/webeditor/frontend/src/components/RenderPanel.jsx` | Reviewed | Not Applicable | Reviewed | Not Applicable | Verified zero bytes; unimplemented scaffold/placeholder |
| `apps/webeditor/frontend/src/components/Timeline.jsx` | Reviewed | Not Applicable | Reviewed | Not Applicable | Verified zero bytes; unimplemented scaffold/placeholder |
| `apps/webeditor/frontend/src/components/Topbar.jsx` | Reviewed | Not Applicable | Reviewed | Not Applicable | Verified zero bytes; unimplemented scaffold/placeholder |
| `apps/webeditor/frontend/src/main.jsx` | Reviewed | Not Applicable | Reviewed | Not Applicable | Verified zero bytes; unimplemented scaffold/placeholder |
| `apps/webeditor/frontend/src/styles/base.css` | Reviewed | Not Applicable | Reviewed | Not Applicable | Verified zero bytes; unimplemented scaffold/placeholder |
| `apps/webeditor/frontend/src/styles/editor.css` | Reviewed | Not Applicable | Reviewed | Not Applicable | Verified zero bytes; unimplemented scaffold/placeholder |
| `apps/webeditor/frontend/src/styles/inspector.css` | Reviewed | Not Applicable | Reviewed | Not Applicable | Verified zero bytes; unimplemented scaffold/placeholder |
| `apps/webeditor/frontend/src/styles/timeline.css` | Reviewed | Not Applicable | Reviewed | Not Applicable | Verified zero bytes; unimplemented scaffold/placeholder |
| `apps/webeditor/frontend/vite.config.js` | Reviewed | Not Applicable | Reviewed | Not Applicable | Verified zero bytes; unimplemented scaffold/placeholder |
| `apps/webeditor/index.html` | Reviewed | Reviewed | Reviewed | Not Applicable | INTEGRATION-019 |
| `apps/webeditor/style.css` | Reviewed | Not Applicable | Reviewed | Not Applicable | No independently evidenced defect; relevant contracts/edge cases inspected |
| `apps/webeditor_legacy/README.md` | Reviewed | Not Applicable | Reviewed | Not Applicable | No independently evidenced defect; relevant contracts/edge cases inspected |
| `apps/webeditor_legacy/backend/main.py` | Reviewed | Reviewed | Reviewed | Reviewed | STATE-021, INTEGRATION-026 |
| `apps/webeditor_legacy/backend/requirements.txt` | Reviewed | Not Applicable | Reviewed | Not Applicable | No independently evidenced defect; relevant contracts/edge cases inspected |
| `apps/webeditor_legacy/frontend/index.html` | Reviewed | Not Applicable | Reviewed | Not Applicable | No independently evidenced defect; relevant contracts/edge cases inspected |
| `apps/webeditor_legacy/frontend/package-lock.json` | Reviewed | Not Applicable | Reviewed | Not Applicable | No independently evidenced defect; relevant contracts/edge cases inspected |
| `apps/webeditor_legacy/frontend/package.json` | Reviewed | Not Applicable | Reviewed | Not Applicable | No independently evidenced defect; relevant contracts/edge cases inspected |
| `apps/webeditor_legacy/frontend/public/fonts/Bernier/Bernier-Regular.ttf` | Reviewed | Not Applicable | Reviewed | Not Applicable | No independently evidenced defect; relevant contracts/edge cases inspected |
| `apps/webeditor_legacy/frontend/public/fonts/Cherry_Bomb_One/CherryBombOne-Regular.ttf` | Reviewed | Not Applicable | Reviewed | Not Applicable | No independently evidenced defect; relevant contracts/edge cases inspected |
| `apps/webeditor_legacy/frontend/public/fonts/Odibee_Sans/OdibeeSans-Regular.ttf` | Reviewed | Not Applicable | Reviewed | Not Applicable | No independently evidenced defect; relevant contracts/edge cases inspected |
| `apps/webeditor_legacy/frontend/src/api.js` | Reviewed | Reviewed | Reviewed | Reviewed | No independently evidenced defect; relevant contracts/edge cases inspected |
| `apps/webeditor_legacy/frontend/src/main.jsx` | Reviewed | Reviewed | Reviewed | Reviewed | UI-035, UI-035, UI-036, UI-036 |
| `apps/webeditor_legacy/frontend/src/styles.css` | Reviewed | Not Applicable | Reviewed | Not Applicable | No independently evidenced defect; relevant contracts/edge cases inspected |
| `apps/webeditor_legacy/frontend/vite.config.js` | Reviewed | Reviewed | Reviewed | Reviewed | No independently evidenced defect; relevant contracts/edge cases inspected |
| `apps/webeditor_legacy/run.bat` | Reviewed | Reviewed | Reviewed | Reviewed | No independently evidenced defect; relevant contracts/edge cases inspected |
| `assets/backgrounds/.gitkeep` | Reviewed | Not Applicable | Reviewed | Not Applicable | Verified zero bytes; unimplemented scaffold/placeholder |
| `assets/backgrounds/01.jpg` | Reviewed | Not Applicable | Reviewed | Not Applicable | No independently evidenced defect; relevant contracts/edge cases inspected |
| `assets/backgrounds/02.jpg` | Reviewed | Not Applicable | Reviewed | Not Applicable | No independently evidenced defect; relevant contracts/edge cases inspected |
| `assets/backgrounds/03.jpg` | Reviewed | Not Applicable | Reviewed | Not Applicable | No independently evidenced defect; relevant contracts/edge cases inspected |
| `assets/backgrounds/04.jpg` | Reviewed | Not Applicable | Reviewed | Not Applicable | No independently evidenced defect; relevant contracts/edge cases inspected |
| `assets/backgrounds/05.jpg` | Reviewed | Not Applicable | Reviewed | Not Applicable | No independently evidenced defect; relevant contracts/edge cases inspected |
| `assets/backgrounds/06.jpg` | Reviewed | Not Applicable | Reviewed | Not Applicable | No independently evidenced defect; relevant contracts/edge cases inspected |
| `assets/backgrounds/07.jpg` | Reviewed | Not Applicable | Reviewed | Not Applicable | No independently evidenced defect; relevant contracts/edge cases inspected |
| `assets/backgrounds/08.jpg` | Reviewed | Not Applicable | Reviewed | Not Applicable | No independently evidenced defect; relevant contracts/edge cases inspected |
| `assets/backgrounds/09.jpg` | Reviewed | Not Applicable | Reviewed | Not Applicable | No independently evidenced defect; relevant contracts/edge cases inspected |
| `assets/backgrounds/10.jpg` | Reviewed | Not Applicable | Reviewed | Not Applicable | No independently evidenced defect; relevant contracts/edge cases inspected |
| `assets/backgrounds/11.jpg` | Reviewed | Not Applicable | Reviewed | Not Applicable | No independently evidenced defect; relevant contracts/edge cases inspected |
| `assets/backgrounds/12.jpg` | Reviewed | Not Applicable | Reviewed | Not Applicable | No independently evidenced defect; relevant contracts/edge cases inspected |
| `assets/backgrounds/13.jpg` | Reviewed | Not Applicable | Reviewed | Not Applicable | No independently evidenced defect; relevant contracts/edge cases inspected |
| `assets/backgrounds/14.jpg` | Reviewed | Not Applicable | Reviewed | Not Applicable | No independently evidenced defect; relevant contracts/edge cases inspected |
| `assets/backgrounds/15.jpg` | Reviewed | Not Applicable | Reviewed | Not Applicable | No independently evidenced defect; relevant contracts/edge cases inspected |
| `assets/backgrounds/16.jpg` | Reviewed | Not Applicable | Reviewed | Not Applicable | No independently evidenced defect; relevant contracts/edge cases inspected |
| `assets/backgrounds/17.jpg` | Reviewed | Not Applicable | Reviewed | Not Applicable | No independently evidenced defect; relevant contracts/edge cases inspected |
| `assets/backgrounds/18.jpg` | Reviewed | Not Applicable | Reviewed | Not Applicable | No independently evidenced defect; relevant contracts/edge cases inspected |
| `assets/backgrounds/19.jpg` | Reviewed | Not Applicable | Reviewed | Not Applicable | No independently evidenced defect; relevant contracts/edge cases inspected |
| `assets/backgrounds/20.jpg` | Reviewed | Not Applicable | Reviewed | Not Applicable | No independently evidenced defect; relevant contracts/edge cases inspected |
| `assets/defaults/logo.png` | Reviewed | Not Applicable | Reviewed | Not Applicable | No independently evidenced defect; relevant contracts/edge cases inspected |
| `assets/defaults/player.png` | Reviewed | Not Applicable | Reviewed | Not Applicable | No independently evidenced defect; relevant contracts/edge cases inspected |
| `assets/fonts/Bernier/Bernier-Regular.ttf` | Reviewed | Not Applicable | Reviewed | Not Applicable | No independently evidenced defect; relevant contracts/edge cases inspected |
| `assets/fonts/Cherry_Bomb_One/CherryBombOne-Regular.ttf` | Reviewed | Not Applicable | Reviewed | Not Applicable | No independently evidenced defect; relevant contracts/edge cases inspected |
| `assets/fonts/Odibee_Sans/OdibeeSans-Regular.ttf` | Reviewed | Not Applicable | Reviewed | Not Applicable | No independently evidenced defect; relevant contracts/edge cases inspected |
| `assets/references/.gitkeep` | Reviewed | Not Applicable | Reviewed | Not Applicable | Verified zero bytes; unimplemented scaffold/placeholder |
| `assets/references/lyrics_video_background_reference.png` | Reviewed | Not Applicable | Reviewed | Not Applicable | No independently evidenced defect; relevant contracts/edge cases inspected |
| `assets/references/upload_thumbnail_reference.png` | Reviewed | Not Applicable | Reviewed | Not Applicable | No independently evidenced defect; relevant contracts/edge cases inspected |
| `data/.gitkeep` | Reviewed | Not Applicable | Reviewed | Not Applicable | Verified zero bytes; unimplemented scaffold/placeholder |
| `data/app_state/.gitkeep` | Reviewed | Not Applicable | Reviewed | Not Applicable | Verified zero bytes; unimplemented scaffold/placeholder |
| `data/songscout/.gitkeep` | Reviewed | Not Applicable | Reviewed | Not Applicable | Verified zero bytes; unimplemented scaffold/placeholder |
| `docs/CLEANUP_NOTES.md` | Reviewed | Not Applicable | Reviewed | Not Applicable | Verified zero bytes; unimplemented scaffold/placeholder |
| `docs/PROJECT_STRUCTURE.md` | Reviewed | Not Applicable | Reviewed | Not Applicable | Verified zero bytes; unimplemented scaffold/placeholder |
| `docs/WORKFLOW.md` | Reviewed | Not Applicable | Reviewed | Not Applicable | Verified zero bytes; unimplemented scaffold/placeholder |
| `docs/renderer_stage1_editor_project.md` | Reviewed | Not Applicable | Reviewed | Not Applicable | No independently evidenced defect; relevant contracts/edge cases inspected |
| `docs/renderer_stage2_webeditor_v2.md` | Reviewed | Not Applicable | Reviewed | Not Applicable | No independently evidenced defect; relevant contracts/edge cases inspected |
| `projects/.gitkeep` | Reviewed | Not Applicable | Reviewed | Not Applicable | Verified zero bytes; unimplemented scaffold/placeholder |
| `pyproject.toml` | Reviewed | Not Applicable | Reviewed | Not Applicable | BUILD-028, BUILD-038 |
| `requirements-heavy.txt` | Reviewed | Not Applicable | Reviewed | Not Applicable | No independently evidenced defect; relevant contracts/edge cases inspected |
| `requirements.txt` | Reviewed | Not Applicable | Reviewed | Not Applicable | BUILD-038 |
| `run.bat` | Reviewed | Reviewed | Reviewed | Reviewed | No independently evidenced defect; relevant contracts/edge cases inspected |
| `scripts/build-web-studio.mjs` | Reviewed | Reviewed | Reviewed | Reviewed | No independently evidenced defect; relevant contracts/edge cases inspected |
| `scripts/clean_cache.bat` | Reviewed | Not Applicable | Reviewed | Not Applicable | Verified zero bytes; unimplemented scaffold/placeholder |
| `scripts/echoforge_router.py` | Reviewed | Reviewed | Reviewed | Reviewed | No independently evidenced defect; relevant contracts/edge cases inspected |
| `scripts/final_cleanup.py` | Reviewed | Reviewed | Reviewed | Reviewed | No independently evidenced defect; relevant contracts/edge cases inspected |
| `scripts/generate_youtube_metadata.py` | Reviewed | Reviewed | Reviewed | Reviewed | No independently evidenced defect; relevant contracts/edge cases inspected |
| `scripts/mark_project_uploaded.py` | Reviewed | Reviewed | Reviewed | Reviewed | STATE-021 |
| `scripts/normalize_project_audio.py` | Reviewed | Reviewed | Reviewed | Reviewed | No independently evidenced defect; relevant contracts/edge cases inspected |
| `scripts/open_editor.bat` | Reviewed | Not Applicable | Reviewed | Not Applicable | Verified zero bytes; unimplemented scaffold/placeholder |
| `scripts/open_webeditor.py` | Reviewed | Reviewed | Reviewed | Reviewed | INTEGRATION-019, INTEGRATION-019, SEC-024, SEC-024, SEC-025 |
| `scripts/open_webeditor_legacy.py` | Reviewed | Reviewed | Reviewed | Reviewed | No independently evidenced defect; relevant contracts/edge cases inspected |
| `scripts/prepare_editor_project.py` | Reviewed | Reviewed | Reviewed | Reviewed | No independently evidenced defect; relevant contracts/edge cases inspected |
| `scripts/prepare_editor_project_v2.py` | Reviewed | Reviewed | Reviewed | Reviewed | No independently evidenced defect; relevant contracts/edge cases inspected |
| `scripts/project_status.py` | Reviewed | Reviewed | Reviewed | Reviewed | STATE-022 |
| `scripts/render_and_upload.py` | Reviewed | Reviewed | Reviewed | Reviewed | No independently evidenced defect; relevant contracts/edge cases inspected |
| `scripts/render_project.py` | Reviewed | Reviewed | Reviewed | Reviewed | FLOW-023 |
| `scripts/render_upload_project.py` | Reviewed | Reviewed | Reviewed | Reviewed | STATE-018, INTEGRATION-019 |
| `scripts/run.bat` | Reviewed | Not Applicable | Reviewed | Not Applicable | Verified zero bytes; unimplemented scaffold/placeholder |
| `scripts/run_router.py` | Reviewed | Reviewed | Reviewed | Reviewed | UPLOAD-020 |
| `scripts/setup.bat` | Reviewed | Not Applicable | Reviewed | Not Applicable | Verified zero bytes; unimplemented scaffold/placeholder |
| `scripts/upload_to_youtube.py` | Reviewed | Reviewed | Reviewed | Reviewed | No independently evidenced defect; relevant contracts/edge cases inspected |
| `scripts/validate_musevault_assets.py` | Reviewed | Reviewed | Reviewed | Reviewed | No independently evidenced defect; relevant contracts/edge cases inspected |
| `scripts/verselock_compare_sources.py` | Reviewed | Reviewed | Reviewed | Reviewed | No independently evidenced defect; relevant contracts/edge cases inspected |
| `scripts/verselock_full_sync.py` | Reviewed | Reviewed | Reviewed | Reviewed | No independently evidenced defect; relevant contracts/edge cases inspected |
| `scripts/verselock_sync.py` | Reviewed | Reviewed | Reviewed | Reviewed | No independently evidenced defect; relevant contracts/edge cases inspected |
| `scripts/verselock_timestamp_transfer.py` | Reviewed | Reviewed | Reviewed | Reviewed | No independently evidenced defect; relevant contracts/edge cases inspected |
| `scripts/verselock_whisper_advanced.py` | Reviewed | Reviewed | Reviewed | Reviewed | No independently evidenced defect; relevant contracts/edge cases inspected |
| `scripts/verselock_whisper_probe.py` | Reviewed | Reviewed | Reviewed | Reviewed | No independently evidenced defect; relevant contracts/edge cases inspected |
| `scripts/workflow_all.py` | Reviewed | Reviewed | Reviewed | Reviewed | FLOW-023, FLOW-023 |
| `scripts/youtube_upload_project.py` | Reviewed | Reviewed | Reviewed | Reviewed | CONFIG-006, UPLOAD-020, STATE-022, UPLOAD-032, UPLOAD-032, TIME-041 |
| `src/echoforge/__init__.py` | Reviewed | Not Applicable | Reviewed | Not Applicable | Verified zero bytes; unimplemented scaffold/placeholder |
| `src/echoforge/__main__.py` | Reviewed | Reviewed | Reviewed | Reviewed | No independently evidenced defect; relevant contracts/edge cases inspected |
| `src/echoforge/cli.py` | Reviewed | Reviewed | Reviewed | Reviewed | LOGIC-002 |
| `src/echoforge/core/__init__.py` | Reviewed | Not Applicable | Reviewed | Not Applicable | Verified zero bytes; unimplemented scaffold/placeholder |
| `src/echoforge/core/config.py` | Reviewed | Reviewed | Reviewed | Reviewed | CONFIG-006 |
| `src/echoforge/core/logging.py` | Reviewed | Reviewed | Reviewed | Reviewed | No independently evidenced defect; relevant contracts/edge cases inspected |
| `src/echoforge/core/paths.py` | Reviewed | Reviewed | Reviewed | Reviewed | No independently evidenced defect; relevant contracts/edge cases inspected |
| `src/echoforge/core/project_builder.py` | Reviewed | Reviewed | Reviewed | Reviewed | STATE-005, STATE-005, STATE-021, STATE-039 |
| `src/echoforge/core/schemas.py` | Reviewed | Reviewed | Reviewed | Reviewed | No independently evidenced defect; relevant contracts/edge cases inspected |
| `src/echoforge/orchestrator.py` | Reviewed | Reviewed | Reviewed | Reviewed | LOGIC-002 |
| `src/echoforge/stages/__init__.py` | Reviewed | Not Applicable | Reviewed | Not Applicable | Verified zero bytes; unimplemented scaffold/placeholder |
| `src/echoforge/stages/musevault/__init__.py` | Reviewed | Reviewed | Reviewed | Reviewed | CONFIG-006 (integration context), MEDIA-007 (integration context), MEDIA-008 (integration context), STATE-009 (integration context), LYRICS-030 (integration context) |
| `src/echoforge/stages/musevault/asset_collector.py` | Reviewed | Reviewed | Reviewed | Reviewed | CONFIG-006 (integration context), MEDIA-007 (integration context), MEDIA-008 (integration context), STATE-009 (integration context), LYRICS-030 (integration context) |
| `src/echoforge/stages/musevault/asset_validator.py` | Reviewed | Reviewed | Reviewed | Reviewed | CONFIG-006 (integration context), MEDIA-007 (integration context), MEDIA-008 (integration context), STATE-009 (integration context), LYRICS-030 (integration context) |
| `src/echoforge/stages/musevault/audio_normalizer.py` | Reviewed | Reviewed | Reviewed | Reviewed | MEDIA-007, MEDIA-008, MEDIA-008, CONFIG-006 (integration context), STATE-009 (integration context), LYRICS-030 (integration context) |
| `src/echoforge/stages/musevault/audio_service.py` | Reviewed | Reviewed | Reviewed | Reviewed | MEDIA-007, CONFIG-006 (integration context), MEDIA-008 (integration context), STATE-009 (integration context), LYRICS-030 (integration context) |
| `src/echoforge/stages/musevault/background_maker.py` | Reviewed | Reviewed | Reviewed | Reviewed | CONFIG-006 (integration context), MEDIA-007 (integration context), MEDIA-008 (integration context), STATE-009 (integration context), LYRICS-030 (integration context) |
| `src/echoforge/stages/musevault/genius_lyrics.py` | Reviewed | Reviewed | Reviewed | Reviewed | CONFIG-006, MEDIA-007 (integration context), MEDIA-008 (integration context), STATE-009 (integration context), LYRICS-030 (integration context) |
| `src/echoforge/stages/musevault/image_service.py` | Reviewed | Reviewed | Reviewed | Reviewed | CONFIG-006 (integration context), MEDIA-007 (integration context), MEDIA-008 (integration context), STATE-009 (integration context), LYRICS-030 (integration context) |
| `src/echoforge/stages/musevault/lyrics_fetcher.py` | Reviewed | Not Applicable | Reviewed | Not Applicable | Verified zero bytes; unimplemented scaffold/placeholder |
| `src/echoforge/stages/musevault/metadata_review.py` | Reviewed | Reviewed | Reviewed | Reviewed | LYRICS-030, CONFIG-006 (integration context), MEDIA-007 (integration context), MEDIA-008 (integration context), STATE-009 (integration context) |
| `src/echoforge/stages/musevault/song_downloader.py` | Reviewed | Not Applicable | Reviewed | Not Applicable | Verified zero bytes; unimplemented scaffold/placeholder |
| `src/echoforge/stages/musevault/synced_lyrics_fetcher.py` | Reviewed | Reviewed | Reviewed | Reviewed | CONFIG-006 (integration context), MEDIA-007 (integration context), MEDIA-008 (integration context), STATE-009 (integration context), LYRICS-030 (integration context) |
| `src/echoforge/stages/musevault/thumbnail_maker.py` | Reviewed | Reviewed | Reviewed | Reviewed | CONFIG-006 (integration context), MEDIA-007 (integration context), MEDIA-008 (integration context), STATE-009 (integration context), LYRICS-030 (integration context) |
| `src/echoforge/stages/renderer/__init__.py` | Reviewed | Reviewed | Reviewed | Reviewed | RENDER-013 (integration context), RENDER-014 (integration context), RENDER-015 (integration context), RENDER-016 (integration context), STATE-018 (integration context), SEC-025 (integration context) |
| `src/echoforge/stages/renderer/editor_project_builder.py` | Reviewed | Reviewed | Reviewed | Reviewed | RENDER-013, RENDER-014 (integration context), RENDER-015 (integration context), RENDER-016 (integration context), STATE-018 (integration context), SEC-025 (integration context) |
| `src/echoforge/stages/renderer/editor_project_v2.py` | Reviewed | Reviewed | Reviewed | Reviewed | SYNC-012, SYNC-012, RENDER-013 (integration context), RENDER-014 (integration context), RENDER-015 (integration context), RENDER-016 (integration context), STATE-018 (integration context), SEC-025 (integration context) |
| `src/echoforge/stages/renderer/exporter.py` | Reviewed | Reviewed | Reviewed | Reviewed | RENDER-013, RENDER-013, RENDER-014, RENDER-014, RENDER-014, RENDER-015, RENDER-015, RENDER-015, RENDER-016, RENDER-016, RENDER-016, RENDER-017, RENDER-017, FLOW-023, SEC-025, SEC-025, STATE-018 (integration context) |
| `src/echoforge/stages/renderer/render_jobs.py` | Reviewed | Reviewed | Reviewed | Reviewed | STATE-018, STATE-018, STATE-039, RENDER-013 (integration context), RENDER-014 (integration context), RENDER-015 (integration context), RENDER-016 (integration context), SEC-025 (integration context) |
| `src/echoforge/stages/renderer/webeditor_renderer.py` | Reviewed | Not Applicable | Reviewed | Not Applicable | Verified zero bytes; unimplemented scaffold/placeholder |
| `src/echoforge/stages/renderer/webeditor_server.py` | Reviewed | Reviewed | Reviewed | Reviewed | SEC-025, RENDER-013 (integration context), RENDER-014 (integration context), RENDER-015 (integration context), RENDER-016 (integration context), STATE-018 (integration context) |
| `src/echoforge/stages/songscout/__init__.py` | Reviewed | Not Applicable | Reviewed | Not Applicable | Verified zero bytes; unimplemented scaffold/placeholder |
| `src/echoforge/stages/songscout/cleaner.py` | Reviewed | Reviewed | Reviewed | Reviewed | DATA-004, DATA-004, CHART-031, CHART-031, LOGIC-001 (integration context), LOGIC-002 (integration context), DATA-003 (integration context), STATE-005 (integration context), TIME-033 (integration context), DB-029 (integration context) |
| `src/echoforge/stages/songscout/database.py` | Reviewed | Reviewed | Reviewed | Reviewed | DATA-003, DATA-003, STATE-005, DB-029, DB-029, TIME-033, LOGIC-001 (integration context), LOGIC-002 (integration context), DATA-004 (integration context) |
| `src/echoforge/stages/songscout/policy.py` | Reviewed | Reviewed | Reviewed | Reviewed | LOGIC-001, TIME-033, LOGIC-002 (integration context), DATA-003 (integration context), DATA-004 (integration context), STATE-005 (integration context), DB-029 (integration context) |
| `src/echoforge/stages/songscout/scraper.py` | Reviewed | Reviewed | Reviewed | Reviewed | LOGIC-001 (integration context), LOGIC-002 (integration context), DATA-003 (integration context), DATA-004 (integration context), STATE-005 (integration context), TIME-033 (integration context), DB-029 (integration context) |
| `src/echoforge/stages/songscout/selector.py` | Reviewed | Reviewed | Reviewed | Reviewed | LOGIC-001 (integration context), LOGIC-002 (integration context), DATA-003 (integration context), DATA-004 (integration context), STATE-005 (integration context), TIME-033 (integration context), DB-029 (integration context) |
| `src/echoforge/stages/tubeharbor/__init__.py` | Reviewed | Reviewed | Reviewed | Reviewed | UPLOAD-020 (integration context), STATE-021 (integration context), CONFIG-006 (integration context), BUILD-028 (integration context) |
| `src/echoforge/stages/tubeharbor/metadata_generator.py` | Reviewed | Reviewed | Reviewed | Reviewed | BUILD-028, UPLOAD-020 (integration context), STATE-021 (integration context), CONFIG-006 (integration context) |
| `src/echoforge/stages/tubeharbor/upload_db.py` | Reviewed | Reviewed | Reviewed | Reviewed | UPLOAD-020, STATE-039, STATE-021 (integration context), CONFIG-006 (integration context), BUILD-028 (integration context) |
| `src/echoforge/stages/tubeharbor/youtube_uploader.py` | Reviewed | Reviewed | Reviewed | Reviewed | CONFIG-006, UPLOAD-020, STATE-021 (integration context), BUILD-028 (integration context), TIME-041 |
| `src/echoforge/stages/verselock/__init__.py` | Reviewed | Reviewed | Reviewed | Reviewed | STATE-009 (integration context), SYNC-010 (integration context), SYNC-011 (integration context), SYNC-012 (integration context), SYNC-040 (integration context) |
| `src/echoforge/stages/verselock/lrc_parser.py` | Reviewed | Reviewed | Reviewed | Reviewed | SYNC-012, STATE-009 (integration context), SYNC-010 (integration context), SYNC-011 (integration context), SYNC-040 (integration context) |
| `src/echoforge/stages/verselock/lyrics_cleaner.py` | Reviewed | Not Applicable | Reviewed | Not Applicable | Verified zero bytes; unimplemented scaffold/placeholder |
| `src/echoforge/stages/verselock/lyrics_whisper_aligner.py` | Reviewed | Reviewed | Reviewed | Reviewed | STATE-009 (integration context), SYNC-010 (integration context), SYNC-011 (integration context), SYNC-012 (integration context), SYNC-040 (integration context) |
| `src/echoforge/stages/verselock/online_lrc_finder.py` | Reviewed | Not Applicable | Reviewed | Not Applicable | Verified zero bytes; unimplemented scaffold/placeholder |
| `src/echoforge/stages/verselock/sync_candidate_ranker.py` | Reviewed | Not Applicable | Reviewed | Not Applicable | Verified zero bytes; unimplemented scaffold/placeholder |
| `src/echoforge/stages/verselock/sync_exporter.py` | Reviewed | Not Applicable | Reviewed | Not Applicable | Verified zero bytes; unimplemented scaffold/placeholder |
| `src/echoforge/stages/verselock/sync_runner.py` | Reviewed | Reviewed | Reviewed | Reviewed | SYNC-010, SYNC-011, STATE-009 (integration context), SYNC-012 (integration context), SYNC-040 (integration context) |
| `src/echoforge/stages/verselock/synced_reuse.py` | Reviewed | Reviewed | Reviewed | Reviewed | STATE-009, SYNC-011, SYNC-010 (integration context), SYNC-012 (integration context), SYNC-040 (integration context) |
| `src/echoforge/stages/verselock/timestamp_transfer.py` | Reviewed | Reviewed | Reviewed | Reviewed | SYNC-010, SYNC-010, SYNC-040, SYNC-040, SYNC-040, STATE-009 (integration context), SYNC-011 (integration context), SYNC-012 (integration context) |
| `src/echoforge/stages/verselock/whisper_advanced.py` | Reviewed | Reviewed | Reviewed | Reviewed | STATE-009, STATE-009, SYNC-010 (integration context), SYNC-011 (integration context), SYNC-012 (integration context), SYNC-040 (integration context) |
| `src/echoforge/stages/verselock/whisper_probe.py` | Reviewed | Reviewed | Reviewed | Reviewed | STATE-009 (integration context), SYNC-010 (integration context), SYNC-011 (integration context), SYNC-012 (integration context), SYNC-040 (integration context) |
| `src/echoforge/utils/__init__.py` | Reviewed | Not Applicable | Reviewed | Not Applicable | Verified zero bytes; unimplemented scaffold/placeholder |
| `src/echoforge/utils/file_utils.py` | Reviewed | Not Applicable | Reviewed | Not Applicable | Verified zero bytes; unimplemented scaffold/placeholder |
| `src/echoforge/utils/image_utils.py` | Reviewed | Not Applicable | Reviewed | Not Applicable | Verified zero bytes; unimplemented scaffold/placeholder |
| `src/echoforge/utils/process_utils.py` | Reviewed | Not Applicable | Reviewed | Not Applicable | Verified zero bytes; unimplemented scaffold/placeholder |
| `src/echoforge/utils/text_utils.py` | Reviewed | Not Applicable | Reviewed | Not Applicable | Verified zero bytes; unimplemented scaffold/placeholder |
| `start_echoforge.bat` | Reviewed | Reviewed | Reviewed | Reviewed | START-034 |
| `tests/__init__.py` | Reviewed | Not Applicable | Reviewed | Reviewed | Verified zero bytes; unimplemented scaffold/placeholder |
| `tests/test_musevault.py` | Reviewed | Not Applicable | Reviewed | Reviewed | Verified zero bytes; unimplemented scaffold/placeholder |
| `tests/test_songscout.py` | Reviewed | Not Applicable | Reviewed | Reviewed | Verified zero bytes; unimplemented scaffold/placeholder |
| `tests/test_verselock.py` | Reviewed | Not Applicable | Reviewed | Reviewed | Verified zero bytes; unimplemented scaffold/placeholder |
| `tests/test_workflow.py` | Reviewed | Not Applicable | Reviewed | Reviewed | Verified zero bytes; unimplemented scaffold/placeholder |
 
### Inspection domains and boundaries

All populated Python files were read and AST-parsed. Syntax/import probes, parameterized SQL, call-site arguments, error propagation, JSON shapes, completion flags, media ordering, inference gates and subprocess lifecycle were reviewed. Frontend source was read fully, including callbacks/effects, capture-order listeners, shared types and CSS/font consumers. Package locks were parsed as declarative graphs rather than audited as vendor implementations. Batch scripts were read; setup/cleanup were not run. The two renderer documents and complete PDF text were used as requirements context, not assumed implementation truth. Three documentation files and four test files are empty.

No credential value was emitted. Code-inspection concerns that lacked enough behavioral evidence are kept as uncertainties or high-confidence/specification findings; generic “may fail” warnings are not treated as confirmed issues.

## 9. Cross-Module Logical Defects

| Traced boundary | Incompatible assumptions | Findings |
|---|---|---|
| Scrape → clean → success marker | Browser returned vs valid chart completed | LOGIC-002, DATA-004, CHART-031 |
| Refresh history → selection | Historical upsert vs current snapshot; read vs claim | LOGIC-001, DATA-003, STATE-005, TIME-033 |
| Project/review → cache → readiness | Existence vs valid current source | MEDIA-007, STATE-009, CONFIG-006 |
| LRC fetch → auto sync | Existing file vs parseable usable timing | SYNC-011, SYNC-012 |
| Whisper → transfer → editor | Candidate/rejected vs approved final | SYNC-010, SYNC-040 |
| Stage-one builder → exporter | Asset pointers vs explicit media clips | RENDER-013 |
| Browser preview → exported MP4 | Pixel units/advertised fields vs heuristics/fallback | RENDER-014, RENDER-015 |
| Modal → capture listener → HTTP → argv | Reviewed metadata/schedule vs alternate protocol | INTEGRATION-019 |
| Save/stage result → parent workflow | Displayed failure/JSON ok=False vs exit success | FLOW-023 |
| Script uploader → module ledger → marker | Separate idempotency/stage/source ownership | UPLOAD-020, STATE-021, STATE-022 |
| Job persistence → reboot | Saved running flag vs live worker | STATE-018, STATE-039 |
| Legacy editor → shared project state | Replacement legacy schema vs durable pipeline identity | STATE-021, SYNC-012 |
| Studio views → included APIs | Proposed lifecycle contracts vs missing services | INTEGRATION-026, UI-027 |

The shared core schemas do not enforce real JSON contracts. A fix limited to one function is insufficient where multiple implementations write the same state/output. Conversely, symptoms from the same root were grouped (e.g. all competing modal/argv fields in INTEGRATION-019) rather than counted repeatedly.

## 10. Scheduling and State-Persistence Issues

There is no installed cron/daemon/daily/monthly worker in maintained source. “Weekly” means eligibility at explicit SongScout invocation. No missed-day replay is present; if strict Friday-only is intentional, document operator force/recovery obligations. Recording host-local completion against configured-zone eligibility is independently defective regardless of that policy choice.

| Scenario (isolated clock or file fixture) | Desired behavior under weekly-window policy | Actual/result | Requirement/evidence |
|---|---|---|---|
| Friday pending | Eligible | True; pass | Implemented |
| Saturday, missed Friday | Catch up | False; fail | Catch-up requirement ambiguous; LOGIC-001 |
| Sunday after Friday success | No repeat | False; pass | Persistence marker supplied to policy fixture |
| Failed Friday, no new success | Retry eligible | True; pass | Does not validate actual error recording path |
| Next Friday | New cycle eligible | True; pass | Exact-date comparison sufficient for this case |
| Two workers before success | One exclusive operation | Both True; fail | Policy offers no claim; actual multi-process execution not run |
| Interrupted before success | Remain eligible | True; pass | Atomic completion/promotion separately defective |
| Thursday 23:59 → Friday 00:00 | Recognize new boundary | False → True; pass | Same-zone naive fixture; actual configured-zone boundary test still needed |
| UTC host / Kolkata Friday | Same cycle completion marker | Different calendar-date sources | Static TIME-033; frozen recorder check not executed |
| Running job restored with no worker | Recover/retry | already_running=True; fail | STATE-018 fixture |
| Invalid final output pair on restart | Rebuild or reject | Reused success; fail | STATE-009 fixture |
| New DB connection after commits | History persists | Used status/date preserved; pass | Isolated SQLite test, not process-kill recovery |

Publication scheduling is delegated to YouTube only after upload. Legacy schedule saving does not install a watcher; its upload worker expects a separate TubeHarbor project outside this repository. Direct uploaders do not parse/validate future-aware timestamps. Accepted past publishAt can publish immediately according to the [official API contract](https://developers.google.com/youtube/v3/docs/videos#status.publishAt); the premature-publication outcome was not tested live (TIME-041).

Additional required temporal cases: delayed retry after schedule becomes stale, clock drift near cycle boundary, configured DST fall-back/fold and spring-forward gaps, unavailable Windows tzdata fallback to UTC, two workers after lease expiry, and interruption after remote insert but before local record. User-zone Kolkata has no seasonal DST, but arbitrary configured zones and browser-local schedule inputs still require explicit semantics.

## 11. Database and Integration Issues

**SQLite facts:** songs ID primary key, title/artist NOT NULL, text statuses, project path and timestamps; metadata key/value primary key; status/rank/title/artist indexes; parameterized queries; application status allowlist. There are no versioned migrations, DB-level status CHECK, unique project-allocation table, membership snapshot, CAS lease or referential project constraint. FOREIGN KEY pragma is set without modeled project references. Upsert correctly preserves used/skipped/failed status; that is useful but does not prove freshness or exclusive claim.

**Observed data:** read-only integrity_check ok; 102 song rows; latest recorded success 2026-07-03; multiple uploaded project snapshots with pending downstream canonical stages. Data was neither reset nor corrected. No assertion that all recorded uploads exist remotely.

**External behavior review:** lyric/image HTTP calls generally have timeouts; malformed/empty response structures, rate-limit retry, pagination/identity/version matching and partial writes are not consistently defended. LRCLIB uses best candidate without a robust reject threshold/duration proof, Genius first-hit selection can mismatch, and parsing can yield unusable timing. These are reliability test obligations, not independently proven wrong live service responses. yt-dlp media identity and FFmpeg partial-output acceptance are directly implicated in cache/normalization findings.

**YouTube:** OAuth refresh/resumable chunks are implemented; retries/backoff/resumable reconciliation/empty response IDs and thumbnail-only failure policy require tests. Root script can report ok=True without a usable returned ID and ignores mark-subprocess status; these symptoms belong to UPLOAD-020/STATE-021/FLOW-023. No real authentication, uploads, account changes or metadata generation calls occurred.

**Gemini:** metadata generation may auto-discover a local key and try external models; opening current render modal can request metadata generation before final approval. Audit intercepted that call. Availability/pricing/account entitlements/model compatibility were not assumed or tested. Whether automatic paid generation on modal open is acceptable is an unresolved product preference rather than a separately confirmed defect.

## 12. Security and Reliability Findings

Confirmed private-path disclosure (SEC-024) requires immediate restriction. SEC-025 describes additional unchecked path/resource surfaces with high confidence and explicit exposure limits. Default local binding helps, but is not an asset authorization policy. Legacy CORS allows broad origins and credentials; no exploitability claim is made from that alone. No confirmed SQL injection or unsafe-pickle-deserialization defect was found in maintained paths; SQL parameters and safe_child/safe_join traversal guards are strengths, though broader authorization remains missing.

Credential storage is excluded from Git by policy, but actual token contents were not inspected. API key use in external request construction, logged subprocess/error tails and unbounded local files need redaction/bounded retention tests; no actual secret leak through logs was asserted. File logger lacks rotation and is not a consistently used observability backbone. Browser/server exceptions often return or log strings without a common stage-failure code; swallowed DB-marking and inferred file readiness hide contradictory outcomes.

Resource risks are concrete: unclosed SQLite contexts (DB-029), deferred stderr draining (RENDER-016), uncontrolled render inputs (SEC-025), in-memory/daemon worker shutdown and direct JSON overwrites (STATE-018/039). Optional CPU inference can be expensive and model downloads depend on environment; these were not run merely to test import success.

## 13. Edge Cases and Missing Tests

| Workflow | Cases requiring regression coverage | Current failure/limit |
|---|---|---|
| Startup/config | Missing env, invalid counts/ports, Python3.10/3.11, direct package install, missing fonts/FFmpeg/tzdata | Config/dependency/runtime contract defects; full clean install not executed |
| Chart | Empty/partial rows, missing hints, numeric/Unicode names, changed DOM, repeated/delayed cycles | Empty success, identity/normalization and temporal ambiguity |
| Selection/project | Exhausted backlog, orphan folder, corrupt state/counter, two workers, completed-project reuse | Wrong latest fallback, downgraded state and unclaimed allocation |
| Assets | Zero/truncated file, changed source, disk-full, unavailable URL, 429, missing defaults | Normalizer false success, stale cache; shared installed assets currently decode |
| Lyrics | Empty/null/malformed response, wrong version/duration, instrumental, non-Latin, repeated timestamps/offset | Schema/parser inconsistencies; wrong live match not established |
| Sync | Sparse/unrelated transcript, failed/cached model, repeated words, end-before-start, approval and interruption | Failed final promotion and weak cache/quality policy |
| Editing | Save500, drag x=0/50, edits during save, project switch, hidden fields, legacy save/rebuild | Failed save proceeds, export mismatch and cross-schema state loss |
| Rendering | Missing audio clip, deleted/muted audio, unsupported font, huge dimensions/FPS, stderr saturation, disk/full permissions | Deterministic audio/index/coordinate defects; soak/load not run |
| Jobs | Reboot, worker death, competing services, stale lock, duplicate request, partial JSON | Permanent active-state guard and no reconciliation |
| Upload | Duplicate retry, empty response, revoked token, network/quota, thumbnail-only fail, crash after insert | Guard bypass/false success/contradictory histories; all remote actions mocked |
| Schedule | Past/naive/future, delayed upload, DST/browser zone, field aliases, private-only publishAt | argv/UI field loss and no temporal validation |
| Studio/legacy | Every API shape, absent external service, first Shift-click, mute/solo, delayed promises and SSE restart | Missing backend, frontend race/scope/cosmetic controls and in-memory jobs |

Requirements to decide before tests encode assumptions: Friday strict-day/catch-up; current chart versus lifetime backlog; manual replacement-upload permission; acceptable timing quality and mandatory approval; missing/background/audio behavior; supported editor and runtime version; paid metadata generation on modal open.

## 14. Executed Tests and Results

### Tool/environment checks

| Executed command/check | Result | Interpretation |
|---|---|---|
| Git root/status + recursive tracked/untracked inventory | Root confirmed; initially clean | All maintained paths catalogued; post-audit diff checked separately |
| AST parse of all 100 maintained Python files on Python3.13.7 | 100 parsed, no syntax failures | Empty files included; does not prove declared older-version compatibility |
| `python -B -m pytest -p no:cacheprovider tests -q` | No tests ran; tool returned exit1 | Four zero-byte test modules; no pass claim |
| `python -B -m ruff check --no-cache --select E9,F821,F811 src scripts apps/webeditor_legacy/backend --output-format concise` | Four diagnostics; exit1 | Three duplicate definitions/imports and one Python3.10 f-string syntax incompatibility; no fixes applied |
| Mypy limited core/SongScout/V2/sync_runner with `--follow-imports skip --ignore-missing-imports` and temp cache | Four errors in 3 files, 14 source files checked | config Path optional args (27/33), database len(object) (385), V2 float optional (86); annotations are not automatically runtime failures |
| `tsc --noEmit --incremental false --project apps/web-studio/frontend/tsconfig.json` | Exit2, 959 diagnostic lines dominated by missing React/types/JSX | Meaningful full Studio typecheck blocked by absent local deps; do not count cascades as 959 confirmed bugs |
| `node --check apps/webeditor/app.js` and `node --check scripts/build-web-studio.mjs` | Both passed | JS parsing only; capture-order semantics still failed browser checks |
| `python -B -m pip check` | Host torchvision0.26.0/torch2.10.0 mismatch | Inference environment concern; dependencies not altered, no clean-install guarantee |
| Read-only actual SQLite integrity/schema/status metadata | integrity_check ok; 102 rows | Database readable; not a logical consistency certification |
| Read-only nine generated project snapshots | All inspected for schema/status/track shape | Uploaded/pending stage contradiction observed; bulk media/log content excluded |
| Two-page PDF text extraction with bundled pypdf | Both pages read | Historical requirements reviewed; no source instructions executed |
| Two npm locks parsed | 38/51 entries, engines/integrities/declaration graph inspected | Registry CVE database not queried; no npm install/build output mutation |

Ruff duplicates: `scripts/open_webeditor.py:28` urlparse; `background_maker.py:135` make_lyrics_video_background; `thumbnail_maker.py:156` make_upload_thumbnail. These are architecture/compatibility shadowing observations rather than inflated duplicate issue counts. Current syntax/import success cannot establish Python3.10 support; [Python3.12 release documentation](https://docs.python.org/3/whatsnew/3.12.html#pep-701-syntactic-formalization-of-f-strings) corroborates BUILD-028.

### Isolated behavioral fixture results

Fixtures live only under the OS temporary directory. SQLite connect calls were patched to temp databases; YouTube client/media and subprocess workers were mocked; model inference was never called. One genuine 320×240, 0.2-second, 5-fps FFmpeg/Pillow MP4 encode ran only in a temporary fixture and passed. Secret-route check patched the root and used a dummy non-secret string. Policy tests patch clock/metadata, so they do not claim a real concurrent operation or UTC/config boundary test.

Initial sandbox run could not access newly created temporary directories. It was rerun with explicit tool escalation. Earlier fixture teardown exposed retained SQLite handles; the harness was corrected to close only its own captured fixture connections. Final run: **32 tests, 9 passed, 23 assertion failures, 0 harness errors**. Harness prints its unittest result and a structured AUDIT_SUMMARY; its shell exit can be zero despite assertion failures, so counts derive from the test runner, not shell success. No production correction was made.

| Test | Result |
|---|---|

| `test_friday_pending` | Passed |

| `test_saturday_missed` | Failed desired-behavior assertion |

| `test_sunday_success_no_duplicate` | Passed |

| `test_friday_failed_retry` | Passed |

| `test_next_friday` | Passed |

| `test_two_workers_exclusive` | Failed desired-behavior assertion |

| `test_friday_interrupted_retry` | Passed |

| `test_friday_boundary` | Passed |

| `test_unicode_ids_unique` | Failed desired-behavior assertion |

| `test_numeric_title` | Failed desired-behavior assertion |

| `test_search_preserves_x` | Failed desired-behavior assertion |

| `test_zero_byte_audio_rejected` | Failed desired-behavior assertion |

| `test_force_audio_distinct_paths` | Failed desired-behavior assertion |

| `test_sync_corrupt_outputs_rebuilt` | Failed desired-behavior assertion |

| `test_failed_transfer_preserves_final` | Failed desired-behavior assertion |

| `test_v2_reads_canonical_json` | Failed desired-behavior assertion |

| `test_stage1_background_visible` | Failed desired-behavior assertion |

| `test_deleted_audio_stays_deleted` | Failed desired-behavior assertion |

| `test_pixel_coordinate_preserved` | Failed desired-behavior assertion |

| `test_missing_audio_filter_indices` | Failed desired-behavior assertion |

| `test_stale_job_restart_recoverable` | Failed desired-behavior assertion |

| `test_failed_upload_not_uploaded` | Failed desired-behavior assertion |

| `test_sqlite_restart_persistence` | Passed |

| `test_old_chart_not_selected` | Failed desired-behavior assertion |

| `test_small_real_render` | Passed |

| `test_root_route_denies_secret_fixture` | Failed desired-behavior assertion |

| `test_current_cli_help_imports` | Passed |

| `test_sqlite_context_closes_connection` | Failed desired-behavior assertion |

| `test_request_json_upload_contract` | Failed desired-behavior assertion |

| `test_scheduling_argument_forwarding` | Failed desired-behavior assertion |

| `test_uploaded_script_guard` | Failed desired-behavior assertion |

| `test_no_song_does_not_resume_other_project` | Failed desired-behavior assertion |


### Fully mocked browser contract test

Playwright Chromium launched headlessly with **every request intercepted**; actual current HTML/JS/CSS were served from source and APIs used fixtures. No local actual editor server or external site was contacted. A valid V2 project loaded without page errors; POST save returned fixture500, generated metadata was fixture-only, user entered APPROVED CUSTOM TITLE/Public and clicked final Render & Upload.

Captured actual request:

```json
{"path":"/api/render-upload-start","body":{"upload":true,"visibility":"private","schedule_time":""}}
```

| Assertion | Result |
|---|---|
| Approved title forwarded | Failed |
| Public visibility forwarded | Failed |
| Render blocked after failed save | Failed |

This validates executable capture-order/save-contract failures, beyond static selector inference. No screenshot was needed: intercepted request payload and assertions directly establish the contract.

### Asset and blocked validation

All 24 first-party JPG/PNG files passed Pillow open/verify and all 6 TTFs loaded successfully: 30 checks passed. No visual composition quality claim follows from decode success. All 200 in-scope files have responsibility/integration coverage, but the following **7 live-validation categories remain blocked or deliberately unexecuted**:

1. Real YouTube chart browser scraping (external changing DOM/network; not necessary to mutate chart DB).
2. Real LRCLIB/Genius matching/rate-limit/auth response validation (no live service correctness claim).
3. Real yt-dlp download/source-format matrix (no media downloads or source cache writes).
4. Full Whisper models/native runtime/accuracy (no model downloads; observed host Torch mismatch).
5. Real YouTube OAuth/upload/publish/thumbnail/reconciliation (destructive/quota external effects forbidden).
6. Real Gemini generation/account/model availability (billable external calls forbidden).
7. Complete Studio typecheck/clean build (missing Studio dependencies; no install or tracked dist rebuild).

Additionally not executed: multi-process project/job races, process-kill/fsync/disk-full faults, long stderr saturation/soak, hostile-origin exploit and full audible/visual preview-export comparison. They are high-confidence/specification/test gaps, not declared failed live tests. These limitations prevent end-to-end production certification, despite full maintained-source inspection.

## 15. Recommended Fixes

Implement corrections only in a follow-up change; this audit did not modify code.

1. Restrict served asset paths immediately and validate authenticated/origin-aware write/render requests (SEC-024/025).
2. Choose one current editor schema, render API and upload implementation. Preserve reviewed metadata/schedule and propagate save/stage failure (INTEGRATION-019/FLOW-023/RENDER-013/014).
3. Establish durable upload logical identity, atomic claim/history and remote-ID reconciliation before allowing retries (UPLOAD-020/STATE-021/022/TIME-041).
4. Gate final timing promotion and validate fingerprinted complete media/sync caches (SYNC-010/011/012, MEDIA-007/008, STATE-009).
5. Reconcile worker leases/locks on restart; atomically coordinate state and project allocation; drain subprocess output (STATE-005/018/039, RENDER-016, DB-029).
6. Resolve scheduling/backlog/quality requirements, then implement explicit cycles/snapshots and a consistent clock (LOGIC-001, DATA-003, TIME-033, SYNC-040).
7. Centralize configuration/dependencies/runtime support and add meaningful isolated CI regressions (CONFIG-006, BUILD-028/038, QA-037). Declare Studio prototype or implement its compatible API before shipping.

Each issue above supplies its smallest reliable correction and dependency-specific regressions. Avoid fixing a route in isolation while another legacy/script route still writes incompatible data or bypasses guards.

## 16. Risk-Based Remediation Priority

| Priority | Findings | Release gate |
|---|---|---|
| Immediate containment | SEC-024, relevant SEC-025 surfaces | Editor cannot serve secrets/private roots or accept arbitrary writes |
| Publication correctness | INTEGRATION-019, UPLOAD-020, STATE-021/022, FLOW-023, TIME-041 | Approved metadata/visibility/output preserved; duplicate/stale/past-schedule retries safe |
| Accepted media correctness | SYNC-010/011/012/040, STATE-009, MEDIA-007/008, RENDER-013/014/015 | Validated accepted outputs match review; rejected attempt preserves previous finals |
| Restart/concurrency | STATE-005/018/039, RENDER-016, DB-029, TIME-033 | Interrupted runs retry without duplicate remote output or ownerless active state |
| Fresh discovery/runtime | LOGIC-001/002, DATA-003/004, CHART-031, CONFIG-006, BUILD-028/038 | Chart policy/identity/input gates and clean supported-runtime checks |
| UI/prototype/maintenance | INTEGRATION-026, UI-027/035/036, START-034, RENDER-017, LYRICS-030, QA-037 | Supported UI paths tested; unsupported prototypes clearly excluded; regressions executed |

Do not equate Medium with optional where it controls a High workflow: field/parser/config/state fixes may be prerequisites. High-confidence risks need targeted dynamic validation before exposure; requirement ambiguities need explicit decisions before coding assertions.

## 17. Remaining Uncertainties

Static maintained-source coverage is complete; **private .env values remain partially reviewed by design**. Secret contents, vendor code, generated duplicates/media and historical snapshots are explicitly excluded, not silently certified. Live API behavior, current remote chart/lyric matching, OAuth/account/model availability and supported clean-install matrix remain unverified. Runtime state samples demonstrate readable files and contradictions, not historical root cause attribution or remote publication truth.

Missing specifications: Friday strict-day/catch-up, accumulated backlog ordering, timing-quality/review gate, replacement-video policy, authoritative editor and output schema, stale schedule handling and automatic Gemini usage. Potential browser-origin exploitation and multi-process/pipe/disk-failure manifestations are not claimed as witnessed events. Module startup passed only on this installed Python3.13 environment.

## 18. Final Audit Conclusion

EchoForge should remain under supervised local operation until the High confirmed correctness/security defects are addressed and risk-specific regression gates pass. Existing outputs, import success and SQLite integrity show useful functionality but are insufficient evidence for unattended production. Highest priorities are private-file containment, one approved-data/render/upload contract, idempotent remote publication, acceptance-safe synchronization, coherent state and restart recovery. This report is an independent inspection and validation artifact, not a code remediation or deployment approval.

### Reproducible fixture harness (no repository test/source edits)

The following exact final harness was executed. Save it outside the repository, update ROOT only if moving the checkout, and use temporary fixture roots. Its mocks deliberately avoid real external calls; it asserts desired behavior, so reproduced defects yield expected failures. This block is evidence, not an instruction to run against production state.

```python

import sys, json, tempfile, sqlite3, importlib.util, subprocess, unittest, os, ast
from pathlib import Path
from unittest.mock import patch
from datetime import datetime
ROOT=Path(r'D:\Hello World\2. Automations\EchoForge')
sys.path.insert(0,str(ROOT/'src'))
sys.dont_write_bytecode=True
from echoforge.stages.songscout import policy, cleaner, database as db
from echoforge.stages.musevault.audio_normalizer import normalize_project_audio
from echoforge.stages.musevault.metadata_review import search_text
from echoforge.stages.verselock.synced_reuse import reuse_existing_synced_lyrics
from echoforge.stages.verselock.timestamp_transfer import timestamp_transfer_sync
from echoforge.stages.renderer import editor_project_v2 as v2, exporter as ex, render_jobs as jobs

def script(name):
    spec=importlib.util.spec_from_file_location('audit_'+name, ROOT/'scripts'/f'{name}.py')
    m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m
status=script('project_status')
class Checks(unittest.TestCase):
    def setUp(self):
        self.connections=[]; self.tmp=tempfile.TemporaryDirectory(prefix='echoforge_audit_'); self.p=Path(self.tmp.name)
    def tearDown(self):
        for c in self.connections: c.close()
        self.tmp.cleanup()
    def temp_connect(self, original, database):
        c=original(database); self.connections.append(c); return c
    def put(self,path,data):
        p=self.p/path; p.parent.mkdir(parents=True,exist_ok=True)
        p.write_text(json.dumps(data) if not isinstance(data,str) else data,encoding='utf-8'); return p
    def decision(self,date,last=None):
        with patch.object(policy,'init_database'),patch.object(policy,'today_local',return_value=datetime.fromisoformat(date)),patch.object(policy,'get_metadata',return_value=last):
            return policy.should_scrape_today().should_scrape
    def test_friday_pending(self): self.assertTrue(self.decision('2026-10-09'))
    def test_saturday_missed(self): self.assertTrue(self.decision('2026-10-10','2026-10-02'))
    def test_sunday_success_no_duplicate(self): self.assertFalse(self.decision('2026-10-11','2026-10-09'))
    def test_friday_failed_retry(self): self.assertTrue(self.decision('2026-10-09','2026-10-02'))
    def test_next_friday(self): self.assertTrue(self.decision('2026-10-16','2026-10-09'))
    def test_two_workers_exclusive(self): self.assertEqual(sum([self.decision('2026-10-09'),self.decision('2026-10-09')]),1)
    def test_friday_interrupted_retry(self): self.assertTrue(self.decision('2026-10-09'))
    def test_friday_boundary(self):
        self.assertFalse(self.decision('2026-10-08T23:59:59','2026-10-02'))
        self.assertTrue(self.decision('2026-10-09T00:00:00','2026-10-02'))
    def test_unicode_ids_unique(self): self.assertNotEqual(cleaner.unique_song_id('\u0917\u0940\u0924','\u0915\u0932\u093e\u0915\u093e\u0930'),cleaner.unique_song_id('\u0938\u0902\u0917\u0940\u0924','\u0917\u093e\u092f\u0915'))
    def test_numeric_title(self): self.assertEqual(cleaner.title_artist_from_lines(['1','7','Singer Name','100 views']),('7','Singer Name'))
    def test_search_preserves_x(self): self.assertEqual(search_text('Taxi'),'Taxi')
    def test_zero_byte_audio_rejected(self):
        self.put('audio/source_audio.m4a',''); self.assertFalse(normalize_project_audio(self.p)['ok'])
    def test_force_audio_distinct_paths(self):
        self.put('audio/source_audio.m4a','dummy')
        commands=[]
        with patch('echoforge.stages.musevault.audio_normalizer.subprocess.run',side_effect=lambda cmd,**kw: commands.append(cmd)),patch('echoforge.stages.musevault.audio_normalizer.shutil.which',return_value='ffmpeg'):
            normalize_project_audio(self.p,force=True)
        self.assertNotEqual(commands[0][3],commands[0][-1])
    def test_sync_corrupt_outputs_rebuilt(self):
        self.put('lyrics/synced_lyrics.lrc','[00:01.00]new lyric\n'); self.put('sync/final_synced_lyrics.lrc','old'); self.put('sync/final_synced_lyrics.json','{')
        result=reuse_existing_synced_lyrics(self.p)
        self.assertFalse(result.get('reused_existing_outputs'))
    def test_failed_transfer_preserves_final(self):
        self.put('lyrics/lyrics.txt','official lyric\n'); self.put('sync/whisper_advanced_transcript.json',{'segments':[{'start':1,'end':2,'text':'one'}]})
        final=self.put('sync/final_synced_lyrics.lrc','GOOD APPROVED FINAL')
        result=timestamp_transfer_sync(self.p,promote=True,use_segments=True)
        self.assertFalse(result['ok']); self.assertEqual(final.read_text(),'GOOD APPROVED FINAL')
    def test_v2_reads_canonical_json(self):
        self.assertIsNotNone(v2.normalize_line({'text':'lyric','start_seconds':1,'end_seconds':2}))
    def test_stage1_background_visible(self):
        from PIL import Image
        bg=self.p/'images/video_background.jpg'; bg.parent.mkdir(); Image.new('RGB',(320,240),(255,0,0)).save(bg)
        # Stage 1 has assets plus top-level lyric clips; exporter only consumes clips.
        data={'assets':{'background':str(bg)},'clips':[{'type':'text','text':'lyric','start':0,'end':1}]}
        pixel=ex.background_at(self.p,ex.clips_from(data),0,(320,240),{}).getpixel((0,0))
        self.assertGreater(pixel[0]-pixel[1],200)
    def test_deleted_audio_stays_deleted(self):
        self.put('audio/source_audio.m4a','dummy'); self.assertIsNone(ex.build_audio(self.p,[],1,self.p))
    def test_pixel_coordinate_preserved(self): self.assertEqual(ex.pos(50,1920,960),50)
    def test_missing_audio_filter_indices(self):
        self.put('good.m4a','dummy'); commands=[]
        clips=[{'type':'audio','src':'missing.m4a','start':0,'end':1},{'type':'audio','src':'good.m4a','start':1,'end':2}]
        with patch.object(ex.subprocess,'run',side_effect=lambda cmd,**kw: commands.append(cmd)):
            ex.build_audio(self.p,clips,2,self.p)
        fc=commands[0][commands[0].index('-filter_complex')+1]; self.assertIn('[0:a]',fc)
    def test_stale_job_restart_recoverable(self):
        jf=self.put('jobs.json',{'old':{'project_dir':str(self.p.resolve()),'status':'running'}})
        saved=jobs._JOBS
        try:
            with patch.object(jobs,'_JOBS_FILE',jf),patch.object(jobs.threading,'Thread'):
                jobs._load_jobs(); result=jobs.start_render_upload_job(self.p,{'upload':False})
                self.assertFalse(result.get('already_running'))
        finally: jobs._JOBS=saved
    def test_failed_upload_not_uploaded(self):
        self.put('upload/youtube_upload_report.json',{'ok':False,'error':'fixture failure'})
        self.assertFalse(status.status(self.p)['stages']['uploaded'])
    def test_sqlite_restart_persistence(self):
        database=self.p/'songs.db'; original=db.connect
        with patch.object(db,'connect',side_effect=lambda *a,**kw:self.temp_connect(original,database)):
            db.upsert_songs([{'id':'one','title':'Title','artist':'Artist','rank':1}]); db.mark_song_status('one','used'); db.set_metadata('last_successful_scrape_date','2026-10-09')
            self.assertEqual(db.get_song('one')['status'],'used'); self.assertEqual(db.get_metadata('last_successful_scrape_date'),'2026-10-09')
    def test_old_chart_not_selected(self):
        database=self.p/'songs.db'; original=db.connect
        with patch.object(db,'connect',side_effect=lambda *a,**kw:self.temp_connect(original,database)):
            db.upsert_songs([{'id':'old','title':'Old','artist':'Artist','rank':1}]); db.upsert_songs([{'id':'fresh','title':'Fresh','artist':'Artist','rank':2}])
            self.assertEqual(db.get_next_available_song()['id'],'fresh')
    def test_small_real_render(self):
        self.put('editor/editor_project.json',{'canvas':{'width':320,'height':240},'clips':[{'type':'text','text':'fixture','start':0,'end':0.2,'x':160,'y':120}]})
        result=ex.export_editor_project(self.p,fps=5); self.assertTrue(result['ok']); self.assertGreater(Path(result['output']).stat().st_size,0)
    def test_root_route_denies_secret_fixture(self):
        server=script('open_webeditor'); self.put('.secrets/dummy.txt','NOT A REAL SECRET')
        handler=object.__new__(server.Handler); handler.path='/root/.secrets/dummy.txt'
        served=[]; handler.send_file=lambda p:served.append(p); handler.send_json=lambda *a,**kw:None; handler.send_text=lambda *a,**kw:None
        with patch.object(server,'ROOT_DIR',self.p): handler.do_GET()
        self.assertEqual(served,[])
    def test_current_cli_help_imports(self):
        env=os.environ.copy(); env['PYTHONPATH']=str(ROOT/'src'); env['PYTHONDONTWRITEBYTECODE']='1'
        p=subprocess.run([sys.executable,'-B','-m','echoforge','--help'],cwd=self.p,env=env,capture_output=True,text=True)
        self.assertEqual(p.returncode,0,p.stderr)
    def test_sqlite_context_closes_connection(self):
        c=db.connect(self.p/'close.db'); self.connections.append(c)
        with c: c.execute('SELECT 1')
        with self.assertRaises(sqlite3.ProgrammingError): c.execute('SELECT 1')
    def test_request_json_upload_contract(self):
        ru=script('render_upload_project'); request=self.put('request.json',{'upload':True,'visibility':'public','title':'approved title'})
        calls=[]
        with patch.object(sys,'argv',['render_upload_project','--project',str(self.p),'--request',str(request)]),patch.object(ru,'run',side_effect=lambda cmd,*a: calls.append(cmd) or subprocess.CompletedProcess(cmd,0,'fixture')):
            ru.main()
        self.assertTrue(any('scripts/youtube_upload_project.py' in cmd for cmd in calls))
    def test_scheduling_argument_forwarding(self):
        ru=script('render_upload_project'); calls=[]
        with patch.object(sys,'argv',['render_upload_project','--project',str(self.p),'--upload','--visibility','schedule','--schedule-time','2026-11-01T10:00:00Z']),patch.object(ru,'run',side_effect=lambda cmd,*a: calls.append(cmd) or subprocess.CompletedProcess(cmd,0,'fixture')):
            ru.main()
        self.assertIn('--schedule-at',calls[-1])
    def test_uploaded_script_guard(self):
        up=script('youtube_upload_project')
        from argparse import Namespace
        from unittest.mock import MagicMock
        from googleapiclient.http import MediaFileUpload
        video=self.put('renders/final_video.mp4','fixture'); self.put('upload/youtube_upload_report.json',{'ok':True,'video_id':'already-done'})
        args=Namespace(video='',thumbnail='',visibility='private',privacy=None,schedule_at='',title='',description='',tags='',category_id='')
        yt=MagicMock(); yt.videos.return_value.insert.return_value.next_chunk.return_value=(None,{'id':'new-upload'})
        with patch.object(up,'build_youtube',return_value=yt),patch('googleapiclient.http.MediaFileUpload'):
            up.upload_video(self.p,args); up.upload_video(self.p,args)
        self.assertEqual(yt.videos.return_value.insert.call_count,0)
    def test_no_song_does_not_resume_other_project(self):
        wf=script('workflow_all'); calls=[]
        def fake(cmd,**kw):
            calls.append(cmd)
            return '{"ok": false, "reason": "No available songs"}' if 'init-next' in cmd else ''
        with patch.object(sys,'argv',['workflow_all','--skip-scrape','--no-popup','--skip-editor-open']),patch.object(wf,'run',side_effect=fake),patch.object(wf,'latest_project',return_value='projects/0001_fixture'):
            try: wf.main()
            except SystemExit: pass
        self.assertFalse(any('collect' in cmd for cmd in calls))
if __name__=='__main__':
    suite=unittest.defaultTestLoader.loadTestsFromTestCase(Checks)
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    summary={'run':result.testsRun,'passed':result.testsRun-len(result.failures)-len(result.errors),'failed':len(result.failures),'errors':len(result.errors),'failures':[x[0].id().split('.')[-1] for x in result.failures],'error_tests':[x[0].id().split('.')[-1] for x in result.errors]}
    (Path(tempfile.gettempdir())/'echoforge_audit_results_01a11e78.json').write_text(json.dumps(summary,indent=2))
    print('AUDIT_SUMMARY '+json.dumps(summary))



```

### Exact mocked-browser harness

```python

import json,os
from pathlib import Path
from playwright.sync_api import sync_playwright
r=Path(r'D:\Hello World\2. Automations\EchoForge'); captured=[]; errors=[]
fixture={'schema':'echoforge.webeditor.v2','project':{'title':'Fixture','artist':'Singer','duration':1},'canvas':{'width':320,'height':240},'assets':{},'tracks':[{'id':'track_lyrics','name':'Lyrics','type':'text','clips':[{'id':'lyric1','type':'text','text':'Fixture lyric','start':0,'end':1,'x':160,'y':120,'style':{'fontFamily':'Arial','fontSize':30,'color':'#000000'}}]}]}
with sync_playwright() as pw:
 browser=pw.chromium.launch(headless=True); page=browser.new_page(); page.on('pageerror',lambda e:errors.append(str(e)))
 def serve(route):
  req=route.request; path=req.url.split('audit.test',1)[-1].split('?')[0]
  if path=='/':route.fulfill(status=200,content_type='text/html',body=(r/'apps/webeditor/index.html').read_text(encoding='utf-8'))
  elif path.endswith('app.js'):route.fulfill(status=200,content_type='application/javascript',body=(r/'apps/webeditor/app.js').read_text(encoding='utf-8'))
  elif path.endswith('style.css'):route.fulfill(status=200,content_type='text/css',body=(r/'apps/webeditor/style.css').read_text(encoding='utf-8'))
  elif path=='/api/project':route.fulfill(status=200 if req.method=='GET' else 500,content_type='application/json',body=json.dumps(fixture if req.method=='GET' else {'ok':False,'error':'fixture save denied'}))
  elif path=='/api/youtube-metadata':route.fulfill(status=200,content_type='application/json',body=json.dumps({'metadata':{'title':'Generated fixture','description':'fixture','tags':[]}}))
  elif req.method=='POST':captured.append({'path':path,'body':req.post_data_json});route.fulfill(status=200,content_type='application/json',body='{"ok":true,"job_id":"fixture"}')
  elif path.startswith('/api'):route.fulfill(status=200,content_type='application/json',body='{"ok":null,"running":false,"phase":"idle"}')
  else:route.fulfill(status=404,body='fixture blocked asset')
 page.route('**/*',serve);page.goto('http://audit.test/');page.wait_for_function("document.getElementById('statusText').textContent.includes('Loaded')")
 page.locator('#efRenderUploadBtn').click();page.locator('.efru-modal [data-title]').wait_for();page.wait_for_function("document.querySelector('.efru-modal [data-title]').value==='Generated fixture'")
 page.locator('.efru-modal [data-title]').fill('APPROVED CUSTOM TITLE');page.locator('.efru-modal [data-visibility]').select_option('public')
 page.locator('.efru-modal [data-render-upload]').click();page.wait_for_timeout(150)
 result={'captured':captured,'page_errors':errors,'checks':{'approved_title_forwarded':any(c['body'].get('metadata',{}).get('title')=='APPROVED CUSTOM TITLE' or c['body'].get('title')=='APPROVED CUSTOM TITLE' for c in captured),'visibility_public_forwarded':any(c['body'].get('visibility')=='public' for c in captured),'render_blocked_after_save_failure':len(captured)==0}}
 print(json.dumps(result,indent=2));(Path(os.environ['TEMP'])/'echoforge_audit_browser_01a11e78.json').write_text(json.dumps(result,indent=2));browser.close()


```
