import { useEffect, useMemo, useRef, useState } from "react";
import { approveTimestamps, fetchTimestamps, projectMediaUrl, saveTimestamps, shiftTimestamps, validateTimestamps } from "../api";
import type { ProjectDetail, TimestampSegment, TimestampsPayload } from "../types";

type SyncEditorProps = {
  project: ProjectDetail | null;
  onProjectChanged: () => Promise<void>;
  setError: (message: string | null) => void;
};

const nudgeSteps = [-1, -0.5, -0.1, 0.1, 0.5, 1];

export function SyncEditor({ project, onProjectChanged, setError }: SyncEditorProps) {
  const editRevision = useRef(0);
  const inFlight = useRef(false);
  const [payload, setPayload] = useState<TimestampsPayload | null>(null);
  const [segments, setSegments] = useState<TimestampSegment[]>([]);
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [dirty, setDirty] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [status, setStatus] = useState<string | null>(null);
  const [currentTime, setCurrentTime] = useState(0);
  const [isPlaying, setIsPlaying] = useState(false);
  const [playbackRate, setPlaybackRate] = useState(1);
  const audioRef = useRef<HTMLAudioElement | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      if (!project) {
        setPayload(null);
        setSegments([]);
        setSelectedIds([]);
        return;
      }
      try {
        const next = normalizePayload(await fetchTimestamps(project.id));
        if (!cancelled) {
          setPayload(next);
          setSegments(next.segments);
          setSelectedIds(next.segments[0] ? [next.segments[0].id] : []);
          setDirty(false);
          setStatus(next.hasDraft ? "Draft loaded" : null);
        }
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Sync timings could not be loaded");
        }
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, [project?.id, setError]);

  const warningBySegment = useMemo(() => {
    const grouped = new Map<string, string[]>();
    for (const warning of payload?.warnings ?? []) {
      if (!warning.segmentId) {
        continue;
      }
      grouped.set(warning.segmentId, [...(grouped.get(warning.segmentId) ?? []), warning.message]);
    }
    return grouped;
  }, [payload?.warnings]);

  const selectedCount = selectedIds.length || segments.length;
  const duration = payload?.duration ?? maxEnd(segments);
  const activeSegment = useMemo(
    () => segments.find((segment) => currentTime >= segment.start && currentTime <= segment.end) ?? null,
    [currentTime, segments],
  );
  const selectedSegments = useMemo(
    () => segments.filter((segment) => selectedIds.includes(segment.id)),
    [segments, selectedIds],
  );

  useEffect(() => {
    if (audioRef.current) {
      audioRef.current.playbackRate = playbackRate;
    }
  }, [playbackRate]);

  if (!project) {
    return (
      <section className="panel">
        <div className="empty-state">
          <strong>Select a project</strong>
        </div>
      </section>
    );
  }

  function commit(nextSegments: TimestampSegment[]) {
    const reindexed = reindexSegments(nextSegments);
    setSegments(reindexed);
    setPayload((current) =>
      current
        ? {
            ...current,
            segments: reindexed,
            segmentCount: reindexed.length,
            duration: maxEnd(reindexed),
          }
        : current,
    );
    editRevision.current += 1;
    setDirty(true);
    setStatus(null);
  }

  function updateSegment(id: string, patch: Partial<TimestampSegment>) {
    commit(segments.map((segment) => (segment.id === id ? { ...segment, ...patch } : segment)));
  }

  function toggleSelected(id: string) {
    setSelectedIds((current) => (current.includes(id) ? current.filter((item) => item !== id) : [...current, id]));
  }

  function toggleAll() {
    setSelectedIds((current) => (current.length === segments.length ? [] : segments.map((segment) => segment.id)));
  }

  function seek(time: number) {
    const next = Math.max(0, Math.min(time, duration || time));
    setCurrentTime(next);
    if (audioRef.current) {
      audioRef.current.currentTime = next;
    }
  }

  async function togglePlayback() {
    const audio = audioRef.current;
    if (!audio) {
      return;
    }
    if (audio.paused) {
      await audio.play().catch(() => setError("Audio could not be played"));
    } else {
      audio.pause();
    }
  }

  function jump(delta: number) {
    seek(currentTime + delta);
  }

  function focusSegment(segment: TimestampSegment) {
    setSelectedIds([segment.id]);
    seek(segment.start);
  }

  function updateSelectedFromPlayhead(field: "start" | "end") {
    const ids = selectedIds.length ? selectedIds : activeSegment ? [activeSegment.id] : [];
    if (!ids.length) {
      return;
    }
    commit(
      segments.map((segment) => {
        if (!ids.includes(segment.id)) {
          return segment;
        }
        if (field === "start") {
          return { ...segment, start: Math.min(roundSeconds(currentTime), Math.max(0, segment.end - 0.05)) };
        }
        return { ...segment, end: Math.max(roundSeconds(currentTime), segment.start + 0.05) };
      }),
    );
  }

  function moveSelectedToPlayhead() {
    const ids = selectedIds.length ? selectedIds : activeSegment ? [activeSegment.id] : [];
    if (!ids.length) {
      return;
    }
    const first = segments.find((segment) => segment.id === ids[0]);
    const anchor = first?.start ?? currentTime;
    const delta = roundSeconds(currentTime - anchor);
    commit(
      segments.map((segment) =>
        ids.includes(segment.id)
          ? {
              ...segment,
              start: Math.max(0, roundSeconds(segment.start + delta)),
              end: Math.max(0.05, roundSeconds(segment.end + delta)),
            }
          : segment,
      ),
    );
  }

  async function nudge(delta: number) {
    if (!project || inFlight.current) return;
    inFlight.current = true;
    const requestedRevision = editRevision.current;
    setBusy(`nudge-${delta}`);
    setError(null);
    try {
      const next = await shiftTimestamps(project.id, segments, delta, selectedIds);
      if (requestedRevision !== editRevision.current) return;
      setSegments(next.segments);
      setPayload((current) =>
        current
          ? {
              ...current,
              segments: next.segments,
              segmentCount: next.segmentCount,
              duration: next.duration,
              warnings: next.warnings,
            }
          : current,
      );
      editRevision.current += 1;
    setDirty(true);
      setStatus(`Nudged ${selectedIds.length ? selectedIds.length : segments.length} row${selectedCount === 1 ? "" : "s"}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Timing nudge failed");
    } finally {
      inFlight.current = false;
      setBusy(null);
    }
  }

  async function validateCurrent() {
    if (!project || inFlight.current) return;
    inFlight.current = true;
    const requestedRevision = editRevision.current;
    setBusy("validate");
    setError(null);
    try {
      const next = await validateTimestamps(project.id, segments);
      if (requestedRevision !== editRevision.current) return;
      setPayload((current) =>
        current
          ? {
              ...current,
              segments: next.segments,
              segmentCount: next.segmentCount,
              duration: next.duration,
              warnings: next.warnings,
            }
          : current,
      );
      setSegments(next.segments);
      setStatus(next.warnings.length ? `${next.warnings.length} warning${next.warnings.length === 1 ? "" : "s"} found` : "No warnings");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Validation failed");
    } finally {
      inFlight.current = false;
      setBusy(null);
    }
  }

  async function saveDraft() {
    if (!project || inFlight.current) return;
    inFlight.current = true;
    const requestedRevision = editRevision.current;
    setBusy("draft");
    setError(null);
    try {
      const next = normalizePayload(await saveTimestamps(project.id, segments, true));
      if (requestedRevision !== editRevision.current) return;
      setPayload(next);
      setSegments(next.segments);
      setDirty(false);
      setStatus("Draft saved");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Sync draft could not be saved");
    } finally {
      inFlight.current = false;
      setBusy(null);
    }
  }

  async function saveCurrent() {
    if (!project || inFlight.current) return;
    inFlight.current = true;
    const requestedRevision = editRevision.current;
    setBusy("save");
    setError(null);
    try {
      const next = normalizePayload(await saveTimestamps(project.id, segments, false));
      if (requestedRevision !== editRevision.current) return;
      setPayload(next);
      setSegments(next.segments);
      setDirty(false);
      setStatus("Saved");
      await onProjectChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Sync timings could not be saved");
    } finally {
      inFlight.current = false;
      setBusy(null);
    }
  }

  async function approveCurrent() {
    if (!project || inFlight.current) return;
    inFlight.current = true;
    const requestedRevision = editRevision.current;
    setBusy("approve");
    setError(null);
    try {
      const next = normalizePayload(await approveTimestamps(project.id, segments));
      if (requestedRevision !== editRevision.current) return;
      setPayload(next);
      setSegments(next.segments);
      setDirty(false);
      setStatus("Approved");
      await onProjectChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Sync timings could not be approved");
    } finally {
      inFlight.current = false;
      setBusy(null);
    }
  }

  return (
    <section className="sync-layout">
      <aside className="sync-side panel">
        <div className="panel-header">
          <h2>Sync</h2>
        </div>
        <div className="lyrics-meta">
          <strong>{project.title}</strong>
          <span>{project.artist}</span>
          <span>{payload?.source === "draft" ? "Draft" : "Current"}</span>
        </div>
        <div className="metric-grid">
          <div className="metric">
            <span>Rows</span>
            <strong>{segments.length}</strong>
          </div>
          <div className="metric">
            <span>Length</span>
            <strong>{formatTime(duration)}</strong>
          </div>
        </div>
        <div className="lyrics-tools">
          <button className="button primary" disabled={Boolean(busy) || !payload} onClick={() => void saveCurrent()} type="button">
            Save
          </button>
          <button className="button" disabled={Boolean(busy) || !payload} onClick={() => void saveDraft()} type="button">
            Save Draft
          </button>
          <button className="button" disabled={Boolean(busy) || !payload} onClick={() => void validateCurrent()} type="button">
            Validate
          </button>
          <button className="button success" disabled={Boolean(busy) || !payload} onClick={() => void approveCurrent()} type="button">
            Approve Sync
          </button>
        </div>
        <div className="save-state">{busy ? "Working..." : status ?? (dirty ? "Unsaved changes" : "Up to date")}</div>
      </aside>

      <section className="sync-editor panel">
        <div className="panel-header">
          <h2>Timing Rows</h2>
          <div className="nudge-grid">
            {nudgeSteps.map((step) => (
              <button className="button small" key={step} onClick={() => void nudge(step)} type="button">
                {step > 0 ? "+" : ""}
                {step.toFixed(step === Math.trunc(step) ? 0 : 1)}s
              </button>
            ))}
          </div>
        </div>

        <div className="transport-panel">
          <audio
            className="audio-player"
            controls
            onEnded={() => setIsPlaying(false)}
            onPause={() => setIsPlaying(false)}
            onPlay={() => setIsPlaying(true)}
            onTimeUpdate={(event) => setCurrentTime(event.currentTarget.currentTime)}
            ref={audioRef}
            src={projectMediaUrl(project.id, "audio")}
          />
          <div className="transport-actions">
            <button className="button small" onClick={() => jump(-5)} type="button">
              -5s
            </button>
            <button className="button primary small" onClick={() => void togglePlayback()} type="button">
              {isPlaying ? "Pause" : "Play"}
            </button>
            <button className="button small" onClick={() => jump(5)} type="button">
              +5s
            </button>
            <button className="button small" onClick={() => updateSelectedFromPlayhead("start")} type="button">
              Set Start
            </button>
            <button className="button small" onClick={() => updateSelectedFromPlayhead("end")} type="button">
              Set End
            </button>
            <button className="button small" onClick={moveSelectedToPlayhead} type="button">
              Move Row
            </button>
            <label className="speed-control">
              <span>Speed</span>
              <select onChange={(event) => setPlaybackRate(Number(event.target.value))} value={playbackRate}>
                {[0.5, 0.75, 1, 1.25, 1.5].map((rate) => (
                  <option key={rate} value={rate}>
                    {rate}x
                  </option>
                ))}
              </select>
            </label>
          </div>
          <div className="transport-readout">
            <strong>{formatTime(currentTime)}</strong>
            <span>{activeSegment ? activeSegment.text : "No active row"}</span>
            <span>{selectedSegments.length ? `${selectedSegments.length} selected` : "Select a row to edit from the playhead"}</span>
          </div>
          <div className="waveform-strip" onClick={(event) => seek((event.nativeEvent.offsetX / event.currentTarget.clientWidth) * Math.max(duration, 1))}>
            <div className="playhead" style={{ left: `${Math.min(100, (currentTime / Math.max(duration, 1)) * 100)}%` }} />
            {segments.map((segment, index) => {
              const timelineDuration = Math.max(duration, 1);
              const left = (segment.start / timelineDuration) * 100;
              const width = Math.max(0.6, ((segment.end - segment.start) / timelineDuration) * 100);
              const active = activeSegment?.id === segment.id;
              const selected = selectedIds.includes(segment.id);
              return (
                <button
                  aria-label={`Select row ${segment.index}`}
                  className={`wave-segment${active ? " active" : ""}${selected ? " selected" : ""}`}
                  key={segment.id}
                  onClick={(event) => {
                    event.stopPropagation();
                    focusSegment(segment);
                  }}
                  style={{ left: `${left}%`, width: `${width}%`, height: `${26 + (index % 5) * 7}px` }}
                  type="button"
                />
              );
            })}
          </div>
        </div>

        <div className="sync-row sync-row-header">
          <label className="sync-check">
            <input checked={segments.length > 0 && selectedIds.length === segments.length} onChange={toggleAll} type="checkbox" />
          </label>
          <span>#</span>
          <span>Start</span>
          <span>End</span>
          <span>Text</span>
        </div>
        <div className="sync-lines">
          {segments.length === 0 ? (
            <div className="empty-state">
              <strong>No timing rows found</strong>
            </div>
          ) : (
            segments.map((segment) => (
              <div className={warningBySegment.has(segment.id) ? "sync-row has-warning" : "sync-row"} key={segment.id}>
                <label className="sync-check">
                  <input checked={selectedIds.includes(segment.id)} onChange={() => toggleSelected(segment.id)} type="checkbox" />
                </label>
                <span className="line-number">{segment.index}</span>
                <input
                  className="time-input"
                  min="0"
                  onChange={(event) => updateSegment(segment.id, { start: readSeconds(event.target.value, segment.start) })}
                  step="0.01"
                  type="number"
                  value={segment.start}
                />
                <input
                  className="time-input"
                  min="0"
                  onChange={(event) => updateSegment(segment.id, { end: readSeconds(event.target.value, segment.end) })}
                  step="0.01"
                  type="number"
                  value={segment.end}
                />
                <input
                  className="segment-text"
                  onChange={(event) => updateSegment(segment.id, { text: event.target.value })}
                  value={segment.text}
                />
                {warningBySegment.has(segment.id) ? (
                  <div className="segment-warning">{warningBySegment.get(segment.id)?.join(", ")}</div>
                ) : null}
              </div>
            ))
          )}
        </div>
      </section>

      <aside className="sync-side panel">
        <div className="panel-header">
          <h2>Warnings</h2>
        </div>
        <div className="warning-list">
          {(payload?.warnings ?? []).length === 0 ? (
            <div className="empty-state">
              <strong>No warnings</strong>
            </div>
          ) : (
            payload?.warnings.map((warning, index) => (
              <div className={`warning-item ${warning.severity}`} key={`${warning.segmentId}-${index}`}>
                <strong>{warning.index ? `Row ${warning.index}` : "Sync"}</strong>
                <span>{warning.message}</span>
              </div>
            ))
          )}
        </div>
        <div className="panel-header versions-header">
          <h2>Versions</h2>
        </div>
        <div className="version-list">
          {(payload?.versions ?? []).slice(0, 8).map((version) => (
            <div className="version-item" key={version.id}>
              <strong>{version.versionLabel}</strong>
              <span>{formatDate(version.createdAt)}</span>
            </div>
          ))}
        </div>
      </aside>
    </section>
  );
}

function normalizePayload(payload: TimestampsPayload): TimestampsPayload {
  const partial = payload as Partial<TimestampsPayload>;
  const segments = Array.isArray(partial.segments) ? partial.segments : [];
  const warnings = Array.isArray(partial.warnings) ? partial.warnings : [];
  const versions = Array.isArray(partial.versions) ? partial.versions : [];
  return {
    projectId: partial.projectId ?? "",
    source: partial.source ?? "current",
    sourcePath: partial.sourcePath ?? "",
    activePath: partial.activePath ?? "",
    draftPath: partial.draftPath ?? "",
    hasDraft: Boolean(partial.hasDraft),
    segmentCount: Number(partial.segmentCount ?? segments.length),
    duration: Number(partial.duration ?? maxEnd(segments)),
    segments,
    warnings,
    versions,
  };
}

function reindexSegments(segments: TimestampSegment[]): TimestampSegment[] {
  return segments.map((segment, index) => ({
    ...segment,
    id: segment.id || `seg_${index + 1}`,
    index: index + 1,
    start: roundSeconds(segment.start),
    end: roundSeconds(segment.end),
    words: Array.isArray(segment.words) ? segment.words : [],
  }));
}

function readSeconds(value: string, fallback: number) {
  const next = Number(value);
  return Number.isFinite(next) ? roundSeconds(Math.max(0, next)) : fallback;
}

function roundSeconds(value: number) {
  return Math.round(value * 1000) / 1000;
}

function maxEnd(segments: TimestampSegment[]) {
  return roundSeconds(segments.reduce((max, segment) => Math.max(max, Number(segment.end) || 0), 0));
}

function formatTime(value: number) {
  const safe = Math.max(0, Number(value) || 0);
  const minutes = Math.floor(safe / 60);
  const seconds = safe - minutes * 60;
  return `${minutes}:${seconds.toFixed(1).padStart(4, "0")}`;
}

function formatDate(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return date.toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}
