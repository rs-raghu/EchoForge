import { useEffect, useMemo, useRef, useState } from "react";
import { approveLyrics, fetchLyrics, saveLyrics } from "../api";
import type { LyricLine, LyricLineType, LyricsPayload, ProjectDetail } from "../types";

type LyricsEditorProps = {
  project: ProjectDetail | null;
  onProjectChanged: () => Promise<void>;
  setError: (message: string | null) => void;
};

const lineTypes: LyricLineType[] = ["lyric", "section_label", "instrumental", "note"];

export function LyricsEditor({ project, onProjectChanged, setError }: LyricsEditorProps) {
  const editRevision = useRef(0);
  const inFlight = useRef(false);
  const [payload, setPayload] = useState<LyricsPayload | null>(null);
  const [lines, setLines] = useState<LyricLine[]>([]);
  const [dirty, setDirty] = useState(false);
  const [autosave, setAutosave] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [status, setStatus] = useState<string | null>(null);
  const [undoStack, setUndoStack] = useState<LyricLine[][]>([]);
  const [redoStack, setRedoStack] = useState<LyricLine[][]>([]);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      if (!project) {
        setPayload(null);
        setLines([]);
        return;
      }
      try {
        const next = await fetchLyrics(project.id);
        if (!cancelled) {
          setPayload(next);
          setLines(next.lines);
          setDirty(false);
          setUndoStack([]);
          setRedoStack([]);
          setStatus(next.hasDraft ? "Draft loaded" : null);
        }
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Lyrics could not be loaded");
        }
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, [project?.id, setError]);

  useEffect(() => {
    if (!project || !autosave || !dirty || busy) {
      return;
    }
    const timer = window.setTimeout(() => {
      void saveDraft();
    }, 1800);
    return () => window.clearTimeout(timer);
  }, [autosave, dirty, busy, lines, project?.id]);

  const warningByLine = useMemo(() => {
    const grouped = new Map<string, string[]>();
    for (const warning of payload?.warnings ?? []) {
      grouped.set(warning.lineId, [...(grouped.get(warning.lineId) ?? []), warning.message]);
    }
    return grouped;
  }, [payload?.warnings]);

  if (!project) {
    return (
      <section className="panel">
        <div className="empty-state">
          <strong>Select a project</strong>
        </div>
      </section>
    );
  }

  function commit(nextLines: LyricLine[]) {
    setUndoStack((stack) => [...stack.slice(-24), lines]);
    setRedoStack([]);
    setLines(reindex(nextLines));
    editRevision.current += 1;
    setDirty(true);
    setStatus(null);
  }

  function updateLine(id: string, patch: Partial<LyricLine>) {
    commit(lines.map((line) => (line.id === id ? { ...line, ...patch } : line)));
  }

  function addLine(afterIndex?: number) {
    const insertAt = typeof afterIndex === "number" ? afterIndex + 1 : lines.length;
    const next = [...lines];
    next.splice(insertAt, 0, blankLine(insertAt + 1));
    commit(next);
  }

  function duplicateLine(index: number) {
    const next = [...lines];
    next.splice(index + 1, 0, { ...lines[index], id: nextId(), timestamp: null });
    commit(next);
  }

  function deleteLine(index: number) {
    if (lines.length <= 1) {
      commit([blankLine(1)]);
      return;
    }
    commit(lines.filter((_, lineIndex) => lineIndex !== index));
  }

  function splitLine(index: number) {
    const line = lines[index];
    const midpoint = Math.max(1, Math.floor(line.text.length / 2));
    const left = line.text.slice(0, midpoint).trim();
    const right = line.text.slice(midpoint).trim();
    const next = [...lines];
    next.splice(index, 1, { ...line, text: left }, { ...line, id: nextId(), text: right, timestamp: null });
    commit(next);
  }

  function mergeWithPrevious(index: number) {
    if (index <= 0) {
      return;
    }
    const previous = lines[index - 1];
    const current = lines[index];
    const merged = { ...previous, text: `${previous.text} ${current.text}`.trim() };
    const next = [...lines];
    next.splice(index - 1, 2, merged);
    commit(next);
  }

  function removeEmptyLines() {
    const filtered = lines.filter((line) => line.text.trim() || line.type !== "lyric");
    commit(filtered.length ? filtered : [blankLine(1)]);
  }

  function formatLyrics() {
    commit(
      lines.map((line) => {
        const text = line.text.replace(/\s+/g, " ").trim();
        return { ...line, text, type: inferType(text, line.type) };
      }),
    );
  }

  function undo() {
    const previous = undoStack[undoStack.length - 1];
    if (!previous) {
      return;
    }
    setUndoStack((stack) => stack.slice(0, -1));
    setRedoStack((stack) => [...stack, lines]);
    setLines(previous);
    editRevision.current += 1;
    setDirty(true);
  }

  function redo() {
    const next = redoStack[redoStack.length - 1];
    if (!next) {
      return;
    }
    setRedoStack((stack) => stack.slice(0, -1));
    setUndoStack((stack) => [...stack, lines]);
    setLines(next);
    editRevision.current += 1;
    setDirty(true);
  }

  async function saveDraft() {
    if (!project || inFlight.current) {
      return;
    }
    inFlight.current = true;
    const requestedRevision = editRevision.current;
    setBusy("draft");
    try {
      const next = await saveLyrics(project.id, lines, true);
      if (requestedRevision !== editRevision.current) return;
      setPayload(next);
      setLines(next.lines);
      setDirty(false);
      setStatus("Draft saved");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Draft could not be saved");
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
    try {
      const next = await saveLyrics(project.id, lines, false);
      if (requestedRevision !== editRevision.current) return;
      setPayload(next);
      setLines(next.lines);
      setDirty(false);
      setStatus("Saved");
      await onProjectChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Lyrics could not be saved");
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
    try {
      const next = await approveLyrics(project.id, lines);
      if (requestedRevision !== editRevision.current) return;
      setPayload(next);
      setLines(next.lines);
      setDirty(false);
      setStatus("Approved");
      await onProjectChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Lyrics could not be approved");
    } finally {
      inFlight.current = false;
      setBusy(null);
    }
  }

  return (
    <section className="lyrics-layout">
      <aside className="lyrics-side panel">
        <div className="panel-header">
          <h2>Song</h2>
        </div>
        <div className="lyrics-meta">
          <strong>{project.title}</strong>
          <span>{project.artist}</span>
          <span>{payload?.format.toUpperCase() ?? "TEXT"}</span>
          <span>{payload?.source === "draft" ? "Draft" : "Current"}</span>
        </div>
        <div className="lyrics-tools">
          <button className="button primary" disabled={Boolean(busy) || !payload} onClick={() => void saveCurrent()} type="button">
            Save
          </button>
          <button className="button" disabled={Boolean(busy) || !payload} onClick={() => void saveDraft()} type="button">
            Save Draft
          </button>
          <button className="button" disabled={!undoStack.length} onClick={undo} type="button">
            Undo
          </button>
          <button className="button" disabled={!redoStack.length} onClick={redo} type="button">
            Redo
          </button>
          <button className="button" onClick={formatLyrics} type="button">
            Format
          </button>
          <button className="button" onClick={removeEmptyLines} type="button">
            Remove Empty
          </button>
          <button className="button success" disabled={Boolean(busy) || !payload} onClick={() => void approveCurrent()} type="button">
            Approve Lyrics
          </button>
        </div>
        <label className="toggle-row">
          <input checked={autosave} onChange={(event) => setAutosave(event.target.checked)} type="checkbox" />
          Auto-save draft
        </label>
        <div className="save-state">{busy ? "Saving..." : status ?? (dirty ? "Unsaved changes" : "Up to date")}</div>
      </aside>

      <section className="lyrics-editor panel">
        <div className="panel-header">
          <h2>Lyrics</h2>
          <button className="button small" onClick={() => addLine()} type="button">
            Add Line
          </button>
        </div>
        <div className="lyric-row lyric-row-header">
          <span>#</span>
          <span>Type</span>
          <span>Text</span>
          <span>Time</span>
          <span />
        </div>
        <div className="lyric-lines">
          {lines.map((line, index) => (
            <div className={warningByLine.has(line.id) ? "lyric-row has-warning" : "lyric-row"} key={line.id}>
              <span className="line-number">{line.index}</span>
              <select value={line.type} onChange={(event) => updateLine(line.id, { type: event.target.value as LyricLineType })}>
                {lineTypes.map((type) => (
                  <option key={type} value={type}>
                    {type.replace("_", " ")}
                  </option>
                ))}
              </select>
              <input value={line.text} onChange={(event) => updateLine(line.id, { text: event.target.value })} />
              <input
                className="time-input"
                value={line.timestamp ?? ""}
                onChange={(event) => updateLine(line.id, { timestamp: event.target.value || null })}
                placeholder="--"
              />
              <div className="line-actions">
                <button className="button small" onClick={() => splitLine(index)} type="button">
                  Split
                </button>
                <button className="button small" disabled={index === 0} onClick={() => mergeWithPrevious(index)} type="button">
                  Merge
                </button>
                <button className="button small" onClick={() => duplicateLine(index)} type="button">
                  Copy
                </button>
                <button className="button small danger subtle" onClick={() => deleteLine(index)} type="button">
                  Delete
                </button>
              </div>
              {warningByLine.has(line.id) ? <div className="line-warning">{warningByLine.get(line.id)?.join(", ")}</div> : null}
            </div>
          ))}
        </div>
      </section>

      <aside className="lyrics-side panel">
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
              <div className={`warning-item ${warning.severity}`} key={`${warning.lineId}-${index}`}>
                <strong>Line {warning.index}</strong>
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

function blankLine(index: number): LyricLine {
  return { id: nextId(), index, type: "lyric", text: "", timestamp: null };
}

function reindex(lines: LyricLine[]): LyricLine[] {
  return lines.map((line, index) => ({ ...line, index: index + 1 }));
}

function nextId() {
  return `line_${Date.now()}_${Math.random().toString(16).slice(2, 8)}`;
}

function inferType(text: string, fallback: LyricLineType): LyricLineType {
  if (!text) {
    return "note";
  }
  if (/^\[[^\]]+\]$/.test(text)) {
    return "section_label";
  }
  if (text.toLowerCase().includes("instrumental")) {
    return "instrumental";
  }
  return fallback === "note" ? "lyric" : fallback;
}

function formatDate(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return date.toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}
