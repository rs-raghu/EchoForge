import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { api } from './api.js';
import './styles.css';

/* ── Helpers ── */
const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
const fmt = (sec) => {
  sec = Math.max(0, Number(sec || 0));
  const m = Math.floor(sec / 60);
  const s = Math.floor(sec % 60);
  const f = Math.floor((sec - Math.floor(sec)) * 100);
  return `${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')}.${String(f).padStart(2,'0')}`;
};
const uid = (p) => `${p}_${Math.random().toString(16).slice(2, 10)}`;

const LYRIC_DEFAULTS_VERSION = 3;
const LYRIC_DEFAULT_STYLE = {
  fontFamily: 'Bernier',
  fontSize: 100,
  color: '#000000',
  strokeColor: '#000000',
  strokeWidth: 0,
  align: 'center',
  opacity: 100,
  letterSpacing: 0,
};

function applyLyricDefaultsToAll(project, markVersion = false) {
  if (!project) return project;
  const width = Number(project.width || 1920);
  const height = Number(project.height || 1080);
  const next = {
    ...project,
    tracks: (project.tracks || []).map(track => {
      if (track.id !== 'lyrics') return track;
      return {
        ...track,
        clips: (track.clips || []).map(clip => ({
          ...clip,
          ...LYRIC_DEFAULT_STYLE,
          x: width / 2,
          y: height / 2,
        })),
      };
    }),
  };
  if (markVersion) next.styleDefaultsAppliedVersion = LYRIC_DEFAULTS_VERSION;
  return next;
}

function ensureProjectLyricDefaults(project) {
  if (!project) return project;
  let next = project;
  if (Number(next.styleDefaultsAppliedVersion || 0) < LYRIC_DEFAULTS_VERSION) {
    next = applyLyricDefaultsToAll(next, true);
  }
  return ensureProjectAudioDefaults(next);
}

function getTrack(project, id) { return project?.tracks?.find(t => t.id === id); }
function allClips(project) { return (project?.tracks || []).flatMap(t => (t.clips||[]).map(c=>({track:t,clip:c}))); }
function findActiveLyric(project, time) {
  const t = getTrack(project, 'lyrics');
  return (t?.clips||[]).find(c => c.visible!==false && time>=Number(c.start) && time<=Number(c.end));
}
function findClip(project, clipId) {
  for (const track of project?.tracks || []) {
    for (const clip of track.clips || []) {
      if (clip.id === clipId) return { track, clip };
    }
  }
  return null;
}
function updateClip(project, clipId, patch) {
  return { ...project, tracks: project.tracks.map(t => ({ ...t, clips: t.clips.map(c => c.id===clipId ? {...c,...patch} : c) })) };
}
function replaceClips(project, trackId, clips) {
  return { ...project, tracks: project.tracks.map(t => t.id===trackId ? {...t,clips} : t) };
}
function updateClipsByIds(project, clipIds, patchOrFactory) {
  const ids = new Set(clipIds || []);
  if (!ids.size) return project;
  return {
    ...project,
    tracks: project.tracks.map(t => ({
      ...t,
      clips: t.clips.map(c => {
        if (!ids.has(c.id) || c.locked) return c;
        const patch = typeof patchOrFactory === 'function' ? patchOrFactory(c, t) : patchOrFactory;
        return { ...c, ...(patch || {}) };
      }),
    })),
  };
}
function deleteClipsByIds(project, clipIds) {
  const ids = new Set(clipIds || []);
  return { ...project, tracks: project.tracks.map(t => ({ ...t, clips: t.clips.filter(c => !ids.has(c.id) || c.locked) })) };
}
function duplicateClipsByIds(project, clipIds) {
  const ids = new Set(clipIds || []);
  let created = [];
  const tracks = project.tracks.map(t => {
    const additions = (t.clips || [])
      .filter(c => ids.has(c.id) && !c.locked)
      .map(c => ({ ...c, id: uid(c.type||'clip'), start: +(Number(c.start||0)+0.5).toFixed(3), end: +(Number(c.end||0)+0.5).toFixed(3) }));
    created.push(...additions.map(c => c.id));
    return { ...t, clips: [...t.clips, ...additions].sort((a,b)=>Number(a.start||0)-Number(b.start||0)) };
  });
  return { project: { ...project, tracks }, created };
}
function lyricClips(project) { return (getTrack(project, 'lyrics')?.clips || []); }

function audioClips(project) { return (getTrack(project, 'audio')?.clips || []); }

function backgroundClips(project) {
  return (getTrack(project, 'background')?.clips || []);
}

function getBackgroundDuration(project) {
  const clips = backgroundClips(project).filter(c => c.visible !== false);
  if (!clips.length) return Number(project.duration || 180);
  return Math.max(
    0.5,
    ...clips.map(c => Number(c.end || 0))
  );
}

function syncProjectDurationToBackground(project) {
  const nextDuration = +getBackgroundDuration(project).toFixed(3);

  return {
    ...project,
    duration: nextDuration,
    tracks: (project.tracks || []).map(track => ({
      ...track,
      clips: (track.clips || []).map(clip => {
        const start = Number(clip.start || 0);
        const end = Number(clip.end || start);

        // Anything after the new duration should be hidden by trimming.
        if (start >= nextDuration) {
          return { ...clip, start: nextDuration, end: nextDuration };
        }

        return {
          ...clip,
          end: Math.min(end, nextDuration),
        };
      }),
    })),
  };
}

function clipStart(clip) { return Number(clip?.start || 0); }
function clipEnd(clip) { return Number(clip?.end || clipStart(clip)); }
function clipDuration(clip) { return Math.max(0, clipEnd(clip) - clipStart(clip)); }
function clipSourceStart(clip) {
  return Number(clip?.sourceStart ?? clip?.source_start ?? 0);
}
function clipSourceEnd(clip) {
  return Number(clip?.sourceEnd ?? clip?.source_end ?? (clipSourceStart(clip) + clipDuration(clip)));
}

function ensureProjectAudioDefaults(project) {
  if (!project) return project;
  const fallbackSrc = project.assets?.audio || '';
  return {
    ...project,
    tracks: (project.tracks || []).map(track => {
      if (track.id !== 'audio') return track;
      return {
        ...track,
        clips: (track.clips || []).map(clip => {
          const start = clipStart(clip);
          const end = clipEnd(clip);
          const sourceStart = Number.isFinite(clipSourceStart(clip)) ? clipSourceStart(clip) : 0;
          const sourceEnd = Number.isFinite(clipSourceEnd(clip)) ? clipSourceEnd(clip) : sourceStart + Math.max(0, end - start);
          return {
            ...clip,
            type: 'audio',
            src: clip.src || fallbackSrc,
            sourceStart: +Math.max(0, sourceStart).toFixed(3),
            sourceEnd: +Math.max(sourceStart + 0.01, sourceEnd).toFixed(3),
            volume: Number(clip.volume ?? 1),
            visible: clip.visible !== false,
          };
        }),
      };
    }),
  };
}

function findActiveAudioClip(project, time) {
  const t = Number(time || 0);
  return audioClips(project)
    .filter(c => c.visible !== false && c.src && t >= clipStart(c) && t < clipEnd(c))
    .sort((a, b) => clipStart(a) - clipStart(b))[0] || null;
}

function splitClipAtTime(clip, time) {
  const t = +Number(time || 0).toFixed(3);
  const start = clipStart(clip);
  const end = clipEnd(clip);
  if (!clip || clip.locked || t <= start || t >= end) return null;

  const left = { ...clip, id: uid(clip.type || 'clip'), end: t };
  const right = { ...clip, id: uid(clip.type || 'clip'), start: t };

  if (clip.type === 'audio') {
    const sourceStart = clipSourceStart(clip);
    const sourceEnd = clipSourceEnd(clip);
    const splitSource = +(sourceStart + (t - start)).toFixed(3);

    left.sourceStart = +sourceStart.toFixed(3);
    left.sourceEnd = +Math.min(sourceEnd, splitSource).toFixed(3);

    right.sourceStart = +Math.min(sourceEnd, splitSource).toFixed(3);
    right.sourceEnd = +sourceEnd.toFixed(3);
  }

  return { left, right };
}


/* ── Undo/Redo stack ── */
function useUndoable(initial) {
  const [state, setState] = useState({ history: [initial], index: 0 });
  const current = state.history[state.index];
  const push = useCallback((updater) => {
    setState(s => {
      const val = typeof updater === 'function' ? updater(s.history[s.index]) : updater;
      const newHist = [...s.history.slice(0, s.index + 1), val].slice(-50);
      return { history: newHist, index: newHist.length - 1 };
    });
  }, []);
  const undo = useCallback(() => setState(s => ({ ...s, index: Math.max(0, s.index-1) })), []);
  const redo = useCallback(() => setState(s => ({ ...s, index: Math.min(s.history.length-1, s.index+1) })), []);
  return [current, push, undo, redo, state.index > 0, state.index < state.history.length - 1];
}

/* ── Unified Clip Action Dispatcher ── */
function useClipActions(updateProject, setSelectedClipId, setSelectedClipIds) {
  const triggerDelete = useCallback((ids) => {
    const targetIds = Array.isArray(ids) ? ids : [ids];
    if (!targetIds.length) return;
    updateProject(p => deleteClipsByIds(p, targetIds));
    setSelectedClipId(null);
    setSelectedClipIds([]);
  }, [updateProject, setSelectedClipId, setSelectedClipIds]);

  const triggerDuplicate = useCallback((ids) => {
    const targetIds = Array.isArray(ids) ? ids : [ids];
    if (!targetIds.length) return;
    updateProject(p => {
      const { project: next, created } = duplicateClipsByIds(p, targetIds);
      setTimeout(() => { setSelectedClipIds(created); setSelectedClipId(created[0] || null); }, 0);
      return next;
    });
  }, [updateProject, setSelectedClipId, setSelectedClipIds]);

  return { triggerDelete, triggerDuplicate };
}

/* ============================================================
   PROJECT PICKER
   ============================================================ */
function ProjectPicker({ onOpen }) {
  const [projects, setProjects] = useState([]);
  const [health, setHealth]     = useState(null);
  const [loading, setLoading]   = useState(true);
  const [error, setError]       = useState('');

  const refresh = useCallback(async () => {
    setLoading(true); setError('');
    try {
      const [h, list] = await Promise.all([api.health(), api.listProjects()]);
      setHealth(h);
      setProjects(list.projects || []);
    } catch(e) { setError(e.message); }
    finally { setLoading(false); }
  }, []);

  useEffect(() => { refresh(); }, [refresh]);

  async function openProject(id, force=false) {
    setError('');
    try {
      const data = await api.bootstrapProject(id, force);
      onOpen(id, data.project);
    } catch(e) { setError(e.message); }
  }

  return (
    <div className="pickerScreen">
      <div className="heroCard">
        <div>
          <div className="eyebrow">EchoForge</div>
          <h1>WebEditor</h1>
          <p>Professional lyrics video editor. Pick a staged project to start editing.</p>
        </div>
        <button className="primary" onClick={refresh}>↻ Refresh</button>
      </div>
      {health && (
        <div className="statusStrip">
          <span>Projects: <b>{health.projectsRoot}</b></span>
          <span className={health.ffmpeg  ? 'pill ok':'pill bad'}>FFmpeg  {health.ffmpeg  ?'✓ ready':'✗ missing'}</span>
          <span className={health.ffprobe ? 'pill ok':'pill bad'}>FFprobe {health.ffprobe ?'✓ ready':'✗ missing'}</span>
        </div>
      )}
      {error   && <div className="errorBox">{error}</div>}
      {loading && <div className="emptyBox">Loading projects…</div>}
      <div className="projectGrid">
        {projects.map(p => (
          <div className="projectCard" key={p.id}>
            <div className="projectTitle">{p.id}</div>
            <div className="projectMeta">
              <span className={p.hasBackground   ? 'pill ok':'pill bad'}>BG</span>
              <span className={p.hasAudio        ? 'pill ok':'pill bad'}>Audio</span>
              <span className={p.hasLyrics       ? 'pill ok':'pill bad'}>Lyrics</span>
              <span className={p.hasEditorProject? 'pill'   :'pill muted'}>{p.hasEditorProject?'Saved':'New'}</span>
            </div>
            <div className="projectActions">
              <button className="primary" onClick={() => openProject(p.id,false)}>Open</button>
              <button onClick={() => openProject(p.id,true)}>Rebuild</button>
            </div>
          </div>
        ))}
      </div>
      {!loading && projects.length===0 && <div className="emptyBox">No projects found. Put WebEditor inside EF/ so it can scan EF/Projects.</div>}
    </div>
  );
}

/* ============================================================
   CONTEXT MENU
   ============================================================ */
function ContextMenu({ x, y, items, onClose }) {
  const ref = useRef(null);
  useEffect(() => {
    const h = (e) => { if (!ref.current?.contains(e.target)) onClose(); };
    window.addEventListener('mousedown', h);
    return () => window.removeEventListener('mousedown', h);
  }, [onClose]);
  return (
    <div ref={ref} className="contextMenu" style={{ top: y, left: x }}>
      {items.map((item, i) =>
        item === 'sep'
          ? <div key={i} className="ctxSep" />
          : <div key={i} className={`ctxItem ${item.danger?'danger':''}`} onMouseDown={() => { item.action(); onClose(); }}>
              {item.icon && <span>{item.icon}</span>}
              {item.label}
            </div>
      )}
    </div>
  );
}

/* ============================================================
   KEYBOARD SHORTCUTS OVERLAY
   ============================================================ */
function ShortcutsOverlay({ onClose }) {
  return (
    <div className="shortcutsOverlay" onClick={onClose}>
      <div className="shortcutsCard" onClick={e => e.stopPropagation()}>
        <h2>⌨ Keyboard Shortcuts</h2>
        <div className="shortcutsGrid">
          {[
            ['Play / Pause',    <kbd>Space</kbd>],
            ['Go to start',     <kbd>Home</kbd>],
            ['Seek −5s',        <kbd>←</kbd>],
            ['Seek +5s',        <kbd>→</kbd>],
            ['Seek −1s',        <kbd>Shift ←</kbd>],
            ['Seek +1s',        <kbd>Shift →</kbd>],
            ['Delete clip',     <kbd>Del</kbd>],
            ['Duplicate clip',  <kbd>Ctrl D</kbd>],
            ['Split clip',      <kbd>S</kbd>],
            ['Undo',            <kbd>Ctrl Z</kbd>],
            ['Redo',            <kbd>Ctrl Y</kbd>],
            ['Add lyric',       <kbd>N</kbd>],
            ['Save',            <kbd>Ctrl S</kbd>],
            ['Close overlay',   <kbd>Esc</kbd>],
          ].map(([label, key]) => (
            <div key={label} className="shortcutRow"><span>{label}</span><span>{key}</span></div>
          ))}
        </div>
        <div style={{marginTop:20,textAlign:'right'}}>
          <button onClick={onClose}>Close</button>
        </div>
      </div>
    </div>
  );
}

/* ============================================================
   PREVIEW CANVAS
   ============================================================ */
function PreviewCanvas({ project, projectId, currentTime, selectedClipId, selectedClipIds, setSelectedClipId, setSelectedClipIds, updateProject, playing, setPlaying }) {
  const wrapRef = useRef(null);
  const shellRef = useRef(null);
  const bgVideoRef = useRef(null);
  const [stageScale, setStageScale] = useState(1);
  const active  = findActiveLyric(project, currentTime);
  const selectedSet = useMemo(() => new Set(selectedClipIds || []), [selectedClipIds]);
  const selected = selectedClipId ? findClip(project, selectedClipId)?.clip : null;
  const displayClip = selected?.type === 'text' ? selected : active;
  const bg = project.assets?.background;
  
  // Determine if the background is a video file
  const isVideoBg = bg && bg.match(/\.(mp4|webm|mov)$/i);

  const scaleInfo = useCallback(() => {
    const rect = wrapRef.current?.getBoundingClientRect();
    if (!rect) return { sx:1, sy:1 };
    return { sx: rect.width/project.width, sy: rect.height/project.height };
  }, [project.width, project.height]);

  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    const update = () => {
      const rect = el.getBoundingClientRect();
      setStageScale(rect.width / Number(project.width || 1920));
    };
    update();
    const ro = new ResizeObserver(update);
    ro.observe(el);
    return () => ro.disconnect();
  }, [project.width]);

  // Sync video background timing to the transport
  useEffect(() => {
    const el = bgVideoRef.current;
    if (!el) return;
    const diff = Math.abs(el.currentTime - currentTime);
    if (diff > 0.25) el.currentTime = currentTime;
  }, [currentTime]);

  useEffect(() => {
    const el = bgVideoRef.current;
    if (!el) return;
    if (playing) el.play().catch(() => {});
    else el.pause();
  }, [playing]);

  function startDragText(e, clip) {
    e.stopPropagation();
    setSelectedClipId(clip.id);
    setSelectedClipIds?.(prev => prev?.includes(clip.id) ? prev : [clip.id]);
    const info = scaleInfo();
    const sx = e.clientX, sy = e.clientY;
    const ox = Number(clip.x || project.width/2);
    const oy = Number(clip.y || project.height/2);
    const move = (ev) => {
      updateProject(p => updateClip(p, clip.id, {
        x: Math.round(clamp(ox + (ev.clientX-sx)/info.sx, 0, p.width)),
        y: Math.round(clamp(oy + (ev.clientY-sy)/info.sy, 0, p.height)),
      }));
    };
    const up = () => { window.removeEventListener('mousemove',move); window.removeEventListener('mouseup',up); };
    window.addEventListener('mousemove', move);
    window.addEventListener('mouseup', up);
  }

  function toggleFullscreen(e) {
    e?.stopPropagation?.();
    const target = shellRef.current;
    if (!target) return;
    if (document.fullscreenElement) document.exitFullscreen?.();
    else target.requestFullscreen?.();
  }

  return (
    <div className="previewPanel">
      <div className="previewHeader">
        <span className="previewTitle">▶ Preview</span>
        <button className="ghost icon-btn" onClick={() => setPlaying(p => !p)} title="Play / Pause (Space)">
          {playing ? '⏸' : '▶'}
        </button>
        <button className="ghost icon-btn" onClick={toggleFullscreen} title="Fullscreen preview">⛶</button>
        <span className="previewTimecode">{fmt(currentTime)}</span>
      </div>
      <div ref={shellRef} className="previewShell" onClick={() => { setSelectedClipId(null); setSelectedClipIds?.([]); }} onDoubleClick={toggleFullscreen}>
        <div ref={wrapRef} className="previewStage" style={{ aspectRatio: `${project.width}/${project.height}` }}>
          {bg
            ? (isVideoBg 
                ? <video ref={bgVideoRef} className="previewBg" src={api.mediaUrl(projectId, bg)} muted playsInline />
                : <img className="previewBg" src={api.mediaUrl(projectId, bg)} alt="" />)
            : <div className="missingAsset">No background · add asset to project folder</div>
          }
          {displayClip && displayClip.visible !== false && (
            <div
              className={`previewLyric ${selectedSet.has(displayClip.id) ? 'selectedText' : ''}`}
              onMouseDown={e => startDragText(e, displayClip)}
              onClick={e => { e.stopPropagation(); setSelectedClipId(displayClip.id); setSelectedClipIds?.([displayClip.id]); }}
              style={{
                left:     `${(Number(displayClip.x || project.width/2)  / project.width ) * 100}%`,
                top:      `${(Number(displayClip.y || project.height/2)/ project.height) * 100}%`,
                fontSize: `${Math.max(12, Number(displayClip.fontSize||50)) * stageScale}px`,
                fontFamily: displayClip.fontFamily || 'Bernier',
                color:    displayClip.color || '#000000',
                textAlign: displayClip.align || 'center',
                WebkitTextStroke: `${Math.max(0,Number(displayClip.strokeWidth||0)) * stageScale}px ${displayClip.strokeColor||'#000'}`,
                lineHeight: 1.12,
                opacity:  displayClip.opacity !== undefined ? displayClip.opacity/100 : 1,
                letterSpacing: `${displayClip.letterSpacing || 0}px`,
              }}
            >
              {displayClip.text}
            </div>
          )}
          {!playing && (
            <button className="bigPlay" onClick={() => setPlaying(true)} title="Play preview (Space)">▶</button>
          )}
        </div>
      </div>
    </div>
  );
}

/* ============================================================
   TRANSPORT BAR
   ============================================================ */
function Transport({ project, projectId, currentTime, setCurrentTime, playing, setPlaying }) {
  const audioRef = useRef(null);
  const timelineRef = useRef(currentTime);
  const projectRef = useRef(project);
  const [volume, setVolume] = useState(100);
  const [muted,  setMuted]  = useState(false);
  const [speed,  setSpeed]  = useState(1);

  const activeAudio = useMemo(() => findActiveAudioClip(project, currentTime), [project, currentTime]);
  const activeSrc = activeAudio?.src || '';

  useEffect(() => { timelineRef.current = currentTime; }, [currentTime]);
  useEffect(() => { projectRef.current = project; }, [project]);

  function timelineToSourceTime(clip, timelineTime) {
    return clipSourceStart(clip) + (Number(timelineTime || 0) - clipStart(clip));
  }

  function sourceToTimelineTime(clip, sourceTime) {
    return clipStart(clip) + (Number(sourceTime || 0) - clipSourceStart(clip));
  }

  // Keep the real audio element aligned to the active timeline audio clip.
  useEffect(() => {
    const el = audioRef.current;
    if (!el) return;

    if (!activeAudio) {
      el.pause();
      return;
    }

    const desired = timelineToSourceTime(activeAudio, currentTime);
    if (Number.isFinite(desired) && Math.abs(el.currentTime - desired) > 0.12) {
      try { el.currentTime = desired; } catch {}
    }

    el.volume = muted ? 0 : volume / 100;
    el.playbackRate = speed;

    if (playing) {
      el.play().catch(() => setPlaying(false));
    } else {
      el.pause();
    }
  }, [activeAudio, activeSrc, currentTime, playing, muted, volume, speed, setPlaying]);

  // Timeline clock: when audio exists, follow audio time; in gaps, advance silently.
  useEffect(() => {
    let raf = 0;
    let last = performance.now();

    const tick = (now) => {
      const dt = Math.max(0, (now - last) / 1000) * speed;
      last = now;

      setCurrentTime(t => {
        const duration = Number(projectRef.current?.duration || 0);
        const clip = findActiveAudioClip(projectRef.current, t);
        const el = audioRef.current;

        if (clip && el && !el.paused) {
          const sourceEnd = clipSourceEnd(clip);
          if (el.currentTime >= sourceEnd - 0.02) {
            el.pause();
            return Math.min(duration, clipEnd(clip));
          }
          return Math.min(duration, sourceToTimelineTime(clip, el.currentTime));
        }

        // No active audio clip means silence/gap. Continue moving the playhead.
        return Math.min(duration || t + dt, t + dt);
      });

      raf = requestAnimationFrame(tick);
    };

    if (playing) raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [playing, speed, setCurrentTime]);

  useEffect(() => {
    if (currentTime >= Number(project.duration || 0) && playing) {
      setPlaying(false);
    }
  }, [currentTime, project.duration, playing, setPlaying]);

  const hasAudioClips = audioClips(project).some(c => c.visible !== false && (c.src || project.assets?.audio));

  return (
    <div className="transport">
      {activeSrc && (
        <audio
          ref={audioRef}
          src={api.mediaUrl(projectId, activeSrc)}
          onEnded={() => {
            const clip = activeAudio;
            if (clip) setCurrentTime(clipEnd(clip));
          }}
        />
      )}
      <button className="primary playBtn" onClick={() => setPlaying(p => !p)} disabled={!hasAudioClips && !project.duration}>
        {playing ? '⏸ Pause' : '▶ Play'}
      </button>
      <button className="ghost icon-btn" onClick={() => setCurrentTime(0)} title="Go to start (Home)">⏮</button>
      <button className="ghost icon-btn" onClick={() => setCurrentTime(t => Math.max(0,t-5))}   title="−5s (←)">−5s</button>
      <button className="ghost icon-btn" onClick={() => setCurrentTime(t => Math.min(project.duration,t+5))} title="+5s (→)">+5s</button>

      <div className="tDivider" />

      <input
        className="timeSlider"
        type="range" min="0" max={project.duration} step="0.01"
        value={currentTime}
        onChange={e => setCurrentTime(Number(e.target.value))}
      />
      <span className="timeReadout">{fmt(currentTime)} / {fmt(project.duration)}</span>

      <div className="tDivider" />

      <div className="volGroup">
        <button className="ghost icon-btn" onClick={() => setMuted(m=>!m)} title="Mute">
          {muted ? '🔇' : volume > 50 ? '🔊' : volume > 0 ? '🔉' : '🔈'}
        </button>
        <input className="volSlider" type="range" min="0" max="100" value={volume}
          onChange={e => { setVolume(Number(e.target.value)); setMuted(false); }} />
      </div>

      <div className="tDivider" />

      <select className="speedSelect" value={speed} onChange={e => setSpeed(Number(e.target.value))} title="Playback speed">
        {[0.25,0.5,0.75,1,1.25,1.5,2].map(s => <option key={s} value={s}>{s}×</option>)}
      </select>

      {activeAudio && (
        <span className="audioSourceReadout" title="Source audio position">
          src {fmt(timelineToSourceTime(activeAudio, currentTime))}
        </span>
      )}
    </div>
  );
}


/* ============================================================
   TIMELINE
   ============================================================ */
function Timeline({ project, currentTime, setCurrentTime, selectedClipId, selectedClipIds, setSelectedClipId, setSelectedClipIds, updateProject, onAddLyric, snap, triggerDelete, triggerDuplicate }) {
  const [zoom, setZoom]   = useState(8);
  const [mutedTracks, setMutedTracks] = useState({});
  const [soloTrack,   setSoloTrack]   = useState(null);
  const [ctxMenu, setCtxMenu]         = useState(null);
  const [clipSearch, setClipSearch]   = useState('');
  const scrollRef  = useRef(null);
  const selectedSet = useMemo(() => new Set(selectedClipIds || []), [selectedClipIds]);
  const lastSelectedClipIdRef = useRef(null);
  const duration   = Math.max(5, Number(project.duration||180));
  const totalWidth = duration * zoom;

  const pxToTime  = useCallback((px) => px/zoom, [zoom]);
  const timeToPx  = useCallback((t)  => t*zoom,  [zoom]);

  useEffect(() => {
    const el = scrollRef.current;
    if (!el || !project.duration) return;
    const px = timeToPx(currentTime) + 168;
    const { scrollLeft, clientWidth } = el;
    if (px < scrollLeft + 30 || px > scrollLeft + clientWidth - 30) {
      el.scrollLeft = Math.max(0, px - clientWidth * 0.35);
    }
  }, [currentTime, timeToPx]);

  function onRulerClick(e) {
    const rect = scrollRef.current.getBoundingClientRect();
    const x = e.clientX - rect.left + scrollRef.current.scrollLeft - 168;
    let t = clamp(pxToTime(x), 0, duration);
    if (snap) t = Math.round(t * 4) / 4;
    setCurrentTime(t);
  }

  function orderedClipIdsForTrack(track) {
    return (track?.clips || [])
      .filter(c => !c.locked)
      .slice()
      .sort((a, b) => Number(a.start || 0) - Number(b.start || 0))
      .map(c => c.id);
  }

  function selectClip(e, clip, track) {
    e.stopPropagation();

    const isToggle = e.ctrlKey || e.metaKey;
    const isRange = e.shiftKey;
    const currentId = clip.id;

    if (isToggle) {
      setSelectedClipIds(prev => {
        const set = new Set(prev || []);
        if (set.has(currentId)) set.delete(currentId);
        else set.add(currentId);

        const arr = Array.from(set);
        setSelectedClipId(arr[arr.length - 1] || null);
        lastSelectedClipIdRef.current = currentId;
        return arr;
      });
      return;
    }

    if (isRange) {
      const anchorId = lastSelectedClipIdRef.current || selectedClipId;
      const orderedIds = orderedClipIdsForTrack(track);
      const anchorIndex = orderedIds.indexOf(anchorId);
      const currentIndex = orderedIds.indexOf(currentId);

      if (anchorIndex !== -1 && currentIndex !== -1) {
        const lo = Math.min(anchorIndex, currentIndex);
        const hi = Math.max(anchorIndex, currentIndex);
        const rangeIds = orderedIds.slice(lo, hi + 1);

        setSelectedClipIds(prev => Array.from(new Set([...(prev || []), ...rangeIds])));
        setSelectedClipId(currentId);
        return;
      }

      setSelectedClipIds(prev => Array.from(new Set([...(prev || []), currentId])));
      setSelectedClipId(currentId);
      lastSelectedClipIdRef.current = currentId;
      return;
    }

    setSelectedClipId(currentId);
    setSelectedClipIds([currentId]);
    lastSelectedClipIdRef.current = currentId;
  }

  function jumpToSearch() {
    const q = clipSearch.trim().toLowerCase();
    if (!q) return;
    const hit = lyricClips(project).find(c => String(c.text || '').toLowerCase().includes(q));
    if (!hit) return;
    setSelectedClipId(hit.id);
    setSelectedClipIds([hit.id]);
    setCurrentTime(Number(hit.start || 0));
    setTimeout(() => {
      const el = scrollRef.current;
      if (el) el.scrollLeft = Math.max(0, timeToPx(Number(hit.start || 0)) - el.clientWidth * 0.35);
    }, 0);
  }

  function selectAllLyrics() {
    const ids = lyricClips(project).filter(c => !c.locked).map(c => c.id);
    setSelectedClipIds(ids);
    setSelectedClipId(ids[0] || null);
  }

  function startClipDrag(e, track, clip, mode) {
    e.stopPropagation();

    // Ctrl/Shift click is for selection, not dragging. Let onClick handle it.
    if ((e.ctrlKey || e.metaKey || e.shiftKey) && mode === 'move') return;

    if (!selectedSet.has(clip.id) || mode !== 'move') {
      setSelectedClipId(clip.id);
      setSelectedClipIds([clip.id]);
      lastSelectedClipIdRef.current = clip.id;
    }
    const startX  = e.clientX;
    const oStart  = Number(clip.start||0);
    const oEnd    = Number(clip.end||oStart+1);
    const movingIds = (mode === 'move' && selectedSet.has(clip.id) && (selectedClipIds || []).length > 1) ? selectedClipIds : [clip.id];
    const originals = allClips(project).filter(({clip:c}) => movingIds.includes(c.id)).map(({clip:c}) => ({ id: c.id, start: Number(c.start||0), end: Number(c.end||0) }));

    const move = (ev) => {
      let dt = (ev.clientX - startX) / zoom;
      if (snap) dt = Math.round(dt * 4) / 4;
      let patch = {};
      if (mode === 'move') {
        const minStart = Math.min(...originals.map(o => o.start));
        const maxEnd = Math.max(...originals.map(o => o.end));
        dt = clamp(dt, -minStart, duration - maxEnd);
        updateProject(p => updateClipsByIds(p, movingIds, c => {
          const original = originals.find(o => o.id === c.id);
          if (!original) return {};
          return { start: +(original.start + dt).toFixed(3), end: +(original.end + dt).toFixed(3) };
        }));
        return;
      } else if (mode === 'left') {
        const newStart = +clamp(oStart+dt, 0, oEnd-0.1).toFixed(3);
        patch = { start: newStart };
        if (clip.type === 'audio') {
          const originalSourceStart = clipSourceStart(clip);
          const originalSourceEnd = clipSourceEnd(clip);
          patch.sourceStart = +clamp(originalSourceStart + (newStart - oStart), 0, originalSourceEnd - 0.1).toFixed(3);
        }
      } else {
        const newEnd = +clamp(oEnd+dt, oStart+0.1, duration).toFixed(3);
        patch = { end: newEnd };
        if (clip.type === 'audio') {
          patch.sourceEnd = +(clipSourceStart(clip) + Math.max(0.1, newEnd - oStart)).toFixed(3);
        }
      }
      updateProject(p => {
  let next = updateClip(p, clip.id, patch);

  const changedBackgroundEnd =
    track?.id === 'background' &&
    Object.prototype.hasOwnProperty.call(patch, 'end');

  if (changedBackgroundEnd) {
    next = syncProjectDurationToBackground(next);
  }

  return next;
});
    };
    const up = () => { window.removeEventListener('mousemove',move); window.removeEventListener('mouseup',up); };
    window.addEventListener('mousemove', move);
    window.addEventListener('mouseup', up);
  }

  function openClipCtx(e, clip) {
    e.preventDefault(); e.stopPropagation();
    setCtxMenu({
      x: e.clientX, y: e.clientY,
      items: [
        { label:'Select',    icon:'↗', action:() => { setSelectedClipId(clip.id); setSelectedClipIds([clip.id]); } },
        { label:'Duplicate', icon:'⧉', action:() => { triggerDuplicate([clip.id]); } },
        'sep',
        { label:'Split at playhead', icon:'✂', action:() => {
          const found = findClip(project, clip.id);
          if (!found) return;
          const pieces = splitClipAtTime(clip, currentTime);
          if (!pieces) return;
          const clips = found.track.clips
            .filter(c => c.id !== clip.id)
            .concat(pieces.left, pieces.right)
            .sort((a,b) => Number(a.start || 0) - Number(b.start || 0));
          updateProject(p => replaceClips(p, found.track.id, clips));
          setSelectedClipId(pieces.right.id);
          setSelectedClipIds([pieces.right.id]);
        }},
        'sep',
        { label:'Delete', icon:'🗑', danger:true, action:() => { if (!clip.locked) triggerDelete([clip.id]); } },
      ],
    });
  }

  const ticks = useMemo(() => {
    const out = [];
    const step = zoom >= 20 ? 1 : zoom >= 10 ? 2 : zoom >= 6 ? 5 : 10;
    for (let t = 0; t <= duration; t += step) {
      out.push({ t, major: Number.isInteger(t/step) });
    }
    return out;
  }, [zoom, duration]);

  const tracks = project.tracks || [];

  return (
    <div className="timelinePanel">
      <div className="timelineToolbar">
        <span className="tlTitle">Timeline</span>
        <div className="tlDivider" />
        <button onClick={onAddLyric} title="Add lyric clip at playhead (N)">＋ Lyric</button>
        <button onClick={selectAllLyrics} title="Select all unlocked lyric clips">☑ Lyrics</button>
        <button onClick={() => { setSelectedClipIds([]); setSelectedClipId(null); }} title="Clear selection">Clear</button>
        {(selectedClipIds || []).length > 1 && <span className="selectionBadge">{selectedClipIds.length} clips selected · drag one to move all</span>}
        <div className="tlDivider" />
        <input className="clipSearch" placeholder="Find lyric…" value={clipSearch} onChange={e => setClipSearch(e.target.value)} onKeyDown={e => { if (e.key === 'Enter') jumpToSearch(); }} />
        <button onClick={jumpToSearch} title="Jump to lyric text">Jump</button>
        <div className="tlDivider" />
        <div className="tlSpacer" />
        <div className="zoomGroup">
          <span>🔍</span>
          <input className="zoomSlider" type="range" min="3" max="40" value={zoom} onChange={e => setZoom(Number(e.target.value))} />
          <span>{zoom}px/s</span>
        </div>
      </div>

      <div ref={scrollRef} className="timelineMain" style={{ overflow:'auto', position:'relative' }}>
        <div className="timelineInner" style={{ width: totalWidth + 168, minHeight: tracks.length * 52 + 52 }}>
          <div className="ruler" style={{ width: totalWidth + 168 }} onClick={onRulerClick}>
            {ticks.map(({ t, major }) => (
              <div key={t} className={`rulerTick ${major?'major':''}`} style={{ left: 168 + timeToPx(t) }}>
                {major ? (t < 60 ? `${t}s` : `${Math.floor(t/60)}:${String(t%60).padStart(2,'0')}`) : ''}
              </div>
            ))}
          </div>

          <div className="playhead" style={{ left: 168 + timeToPx(currentTime) }} />

          {tracks.map(track => (
            <div className="trackRow" key={track.id}>
              <div className="trackLabel">
                <div className={`trackDot ${track.type||''}`} />
                <span className="trackLabelName" title={track.name||track.id}>{track.name||track.id}</span>
                <div className="trackControls">
                  <button className={`icon-btn ${mutedTracks[track.id]?'trackActive':''}`} title="Mute track" onClick={() => setMutedTracks(m => ({...m,[track.id]:!m[track.id]}))}>M</button>
                  <button className={`icon-btn ${soloTrack===track.id?'trackActive':''}`} title="Solo track" onClick={() => setSoloTrack(s => s===track.id ? null : track.id)}>S</button>
                </div>
              </div>
              <div className={`trackArea ${track.type||''}`} style={{ width: totalWidth }}>
                {(track.clips||[]).map(clip => {
                  const start = Number(clip.start||0);
                  const end   = Number(clip.end||start+1);
                  return (
                    <div
                      key={clip.id}
                      className={`clip ${clip.type||track.type||''} ${selectedSet.has(clip.id)?'selectedClip':''}`}
                      style={{ left: timeToPx(start), width: Math.max(6, timeToPx(end-start)) }}
                      onMouseDown={e => !clip.locked && startClipDrag(e, track, clip, 'move')}
                      onClick={e => selectClip(e, clip, track)}
                      onContextMenu={e => openClipCtx(e, clip)}
                      title={`${clip.text||clip.src||clip.id}\n${fmt(start)} → ${fmt(end)}${clip.type==='audio' ? `\nsource ${fmt(clipSourceStart(clip))} → ${fmt(clipSourceEnd(clip))}` : ''}`}
                    >
                      {!clip.locked && <span className="handle left"  onMouseDown={e => startClipDrag(e, track, clip, 'left')}  />}
                      <span className="clipText">{clip.text||clip.src||clip.id}</span>
                      {!clip.locked && <span className="handle right" onMouseDown={e => startClipDrag(e, track, clip, 'right')} />}
                    </div>
                  );
                })}
              </div>
            </div>
          ))}
        </div>
      </div>

      {ctxMenu && <ContextMenu x={ctxMenu.x} y={ctxMenu.y} items={ctxMenu.items} onClose={() => setCtxMenu(null)} />}
    </div>
  );
}

/* ============================================================
   PROPERTIES PANEL
   ============================================================ */
function PropertiesPanel({ project, selectedClipId, selectedClipIds, updateProject, triggerDelete, triggerDuplicate }) {
  const result = selectedClipId ? findClip(project, selectedClipId) : null;
  const clip   = result?.clip;
  const [tab, setTab] = useState('style');

  function patch(data) {
    const targetIds = (selectedClipIds && selectedClipIds.length > 0) ? selectedClipIds : [clip.id];

    updateProject(p => {
      let next = updateClipsByIds(p, targetIds, data);

      const changedBackgroundEnd =
        clip?.type === 'image' &&
        result?.track?.id === 'background' &&
        Object.prototype.hasOwnProperty.call(data, 'end');

      if (changedBackgroundEnd) {
        next = syncProjectDurationToBackground(next);
      }

      return next;
    });
    }

  function applyToAllLyrics(data) { updateProject(p => updateClipsByIds(p, lyricClips(p).map(c => c.id), data)); }
  function applySelectedStyleToAllLyrics(keys) {
    if (!clip) return;
    const data = {};
    keys.forEach(k => { data[k] = clip[k]; });
    applyToAllLyrics(data);
  }

  const FONTS = ['Bernier','Arial','Georgia','Impact','Courier New','Verdana','Trebuchet MS','Times New Roman','Comic Sans MS'];

  return (
    <div className="propsPanel">
      <div className="propsPanelHeader">
        <span className="propsPanelTitle">Properties</span>
        {clip?.type === 'text' && (
          <div className="propsTabBar">
            <button className={tab==='style'?'active':''} onClick={() => setTab('style')}>Style</button>
            <button className={tab==='timing'?'active':''} onClick={() => setTab('timing')}>Timing</button>
          </div>
        )}
      </div>

      <div className="propsPanelBody">
        {!clip ? (
          <div className="empty">
            <div style={{fontSize:28,marginBottom:8}}>⬜</div>
            Select a clip on the timeline<br/>to edit its properties.
          </div>
        ) : (
          <>
            <div className="propId">{clip.id}{(selectedClipIds || []).length > 1 ? ` · ${selectedClipIds.length} selected` : ''}</div>

            {(clip.type !== 'text' || tab === 'timing') && (
              <div className="propSection">
                <div className="propSectionTitle">Timing</div>
                <div className="twoCols">
                  <label>Start (s)<input type="number" step="0.01" value={clip.start} disabled={clip.locked} onChange={e => patch({ start: Number(e.target.value) })} /></label>
                  <label>End (s)<input type="number" step="0.01" value={clip.end} disabled={clip.locked} onChange={e => patch({ end: Number(e.target.value) })} /></label>
                </div>
                <label style={{color:'var(--text-muted)',fontSize:11}}>Duration: {(Number(clip.end)-Number(clip.start)).toFixed(2)}s</label>
                {clip.type === 'audio' && (
                  <>
                    <div className="twoCols" style={{marginTop:8}}>
                      <label>Source start (s)<input type="number" step="0.01" value={clip.sourceStart ?? 0} disabled={clip.locked} onChange={e => patch({ sourceStart: Number(e.target.value) })} /></label>
                      <label>Source end (s)<input type="number" step="0.01" value={clip.sourceEnd ?? (Number(clip.sourceStart || 0) + Number(clip.end || 0) - Number(clip.start || 0))} disabled={clip.locked} onChange={e => patch({ sourceEnd: Number(e.target.value) })} /></label>
                    </div>
                    <label>Clip volume
                      <div className="rangeRow">
                        <input type="range" min="0" max="2" step="0.01" value={clip.volume ?? 1} disabled={clip.locked} onChange={e => patch({ volume: Number(e.target.value) })} />
                        <span className="rangeVal">{Number(clip.volume ?? 1).toFixed(2)}×</span>
                      </div>
                    </label>
                  </>
                )}
              </div>
            )}

            {clip.type === 'text' && tab === 'style' && (
              <>
                <div className="propSection">
                  <div className="propSectionTitle">Text</div>
                  <label>Content<textarea value={clip.text||''} onChange={e => patch({text:e.target.value})} /></label>
                  <label>Font family
                    <select value={clip.fontFamily||'Bernier'} onChange={e => patch({fontFamily:e.target.value})}>
                      {FONTS.map(f => <option key={f} value={f}>{f}</option>)}
                    </select>
                  </label>
                  <button onClick={() => applySelectedStyleToAllLyrics(['fontFamily'])}>Apply font to all lyrics</button>
                  <label>Font size
                    <div className="rangeRow">
                      <input type="range" min="16" max="200" value={clip.fontSize||50} onChange={e => patch({fontSize:Number(e.target.value)})} />
                      <span className="rangeVal">{clip.fontSize||50}px</span>
                    </div>
                  </label>
                  <button onClick={() => applySelectedStyleToAllLyrics(['fontSize'])}>Apply size to all lyrics</button>
                  <label>Alignment
                    <div className="alignBtns">
                      {[['left','⬅'],['center','↔'],['right','➡']].map(([a,icon]) => (
                        <button key={a} className={(clip.align||'center')===a?'active':'ghost'} onClick={() => patch({align:a})}>{icon}</button>
                      ))}
                    </div>
                  </label>
                  <label>Letter spacing
                    <div className="rangeRow">
                      <input type="range" min="-5" max="30" value={clip.letterSpacing||0} onChange={e => patch({letterSpacing:Number(e.target.value)})} />
                      <span className="rangeVal">{clip.letterSpacing||0}px</span>
                    </div>
                  </label>
                </div>

                <div className="propSection">
                  <div className="propSectionTitle">Appearance</div>
                  <label>Fill color
                    <div className="colorRow">
                      <input type="color" value={clip.color||'#000000'} onChange={e => patch({color:e.target.value})} />
                      <input className="colorHexInput" type="text" value={clip.color||'#000000'} onChange={e => patch({color:e.target.value})} />
                    </div>
                  </label>
                  <label>Stroke color
                    <div className="colorRow">
                      <input type="color" value={clip.strokeColor||'#000000'} onChange={e => patch({strokeColor:e.target.value})} />
                      <input className="colorHexInput" type="text" value={clip.strokeColor||'#000000'} onChange={e => patch({strokeColor:e.target.value})} />
                    </div>
                  </label>
                  <label>Stroke width
                    <div className="rangeRow">
                      <input type="range" min="0" max="20" value={clip.strokeWidth||0} onChange={e => patch({strokeWidth:Number(e.target.value)})} />
                      <span className="rangeVal">{clip.strokeWidth||0}px</span>
                    </div>
                  </label>
                  <label>Opacity
                    <div className="rangeRow">
                      <input type="range" min="0" max="100" value={clip.opacity!==undefined?clip.opacity:100} onChange={e => patch({opacity:Number(e.target.value)})} />
                      <span className="rangeVal">{clip.opacity!==undefined?clip.opacity:100}%</span>
                    </div>
                  </label>
                  <button onClick={() => applySelectedStyleToAllLyrics(['color','strokeColor','strokeWidth','opacity','letterSpacing','align'])}>Apply appearance to all lyrics</button>
                </div>

                <div className="propSection">
                  <div className="propSectionTitle">Position</div>
                  <div className="twoCols">
                    <label>X<input type="number" value={Math.round(clip.x||0)} onChange={e => patch({x:Number(e.target.value)})} /></label>
                    <label>Y<input type="number" value={Math.round(clip.y||0)} onChange={e => patch({y:Number(e.target.value)})} /></label>
                  </div>
                  <div className="threeCols" style={{marginTop:6}}>
                    {[
                      ['TL','top-left',     [0,               0                ]],
                      ['TC','top-center',   [project.width/2, 0                ]],
                      ['TR','top-right',    [project.width,   0                ]],
                      ['ML','mid-left',     [0,               project.height/2 ]],
                      ['MC','center',       [project.width/2, project.height/2 ]],
                      ['MR','mid-right',    [project.width,   project.height/2 ]],
                      ['BL','bottom-left',  [0,               project.height-80]],
                      ['BC','bottom-center',[project.width/2, project.height-80]],
                      ['BR','bottom-right', [project.width,   project.height-80]],
                    ].map(([label, title, [x,y]]) => (
                      <button key={label} className="ghost" title={title} style={{fontSize:10,padding:'3px'}} onClick={() => patch({x:Math.round(x),y:Math.round(y)})}>{label}</button>
                    ))}
                  </div>
                  <button onClick={() => applySelectedStyleToAllLyrics(['x','y','align'])}>Apply position to all lyrics</button>
                </div>
              </>
            )}

            <div className="propSection">
              <label className="checkLine"><input type="checkbox" checked={clip.visible!==false} onChange={e => patch({visible:e.target.checked})} />Visible</label>
              <label className="checkLine"><input type="checkbox" checked={!!clip.locked} onChange={e => patch({locked:e.target.checked})} />Locked</label>
            </div>

            <div className="propActions">
              <button onClick={() => triggerDuplicate([clip.id])} disabled={clip.locked} title="Ctrl+D">⧉ Duplicate</button>
              <button className="danger" onClick={() => triggerDelete([clip.id])} disabled={clip.locked} title="Del">🗑 Delete</button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

/* ============================================================
   EDITOR
   ============================================================ */
function Editor({ projectId, initialProject, onBack }) {
  const normalizedInitialProject = useMemo(() => ensureProjectLyricDefaults(initialProject), [initialProject]);
  const [project, updateProject, undo, redo, canUndo, canRedo] = useUndoable(normalizedInitialProject);
  const [currentTime, setCurrentTime] = useState(0);
  const [playing,      setPlaying]    = useState(false);
  const [selectedClipId, setSelectedClipId] = useState(null);
  const [selectedClipIds, setSelectedClipIds] = useState([]);
  const [status,  setStatus]   = useState('');
  const [error,   setError]    = useState('');
  const [renderResult, setRenderResult] = useState(null);
  const [showShortcuts, setShowShortcuts] = useState(false);
  const [snap, setSnap] = useState(false);
  const [uploadPrivacy, setUploadPrivacy] = useState('scheduled');
  const [publishAt, setPublishAt] = useState('');
  const [renderJob, setRenderJob] = useState(null);
  
  const esRef = useRef(null);

  const { triggerDelete, triggerDuplicate } = useClipActions(updateProject, setSelectedClipId, setSelectedClipIds);

  /* ── EventSource Cleanup ── */
  useEffect(() => {
    return () => {
      if (esRef.current) esRef.current.close();
    };
  }, []);

  /* ── Keyboard shortcuts ── */
  useEffect(() => {
    const onKey = (e) => {
      const tag = e.target?.tagName?.toLowerCase();
      if (tag === 'input' || tag === 'textarea' || tag === 'select') return;

      if (e.code === 'Space') { e.preventDefault(); setPlaying(p => !p); return; }
      if (e.code === 'Home')  { e.preventDefault(); setCurrentTime(0); return; }
      if (e.code === 'ArrowLeft')  { e.preventDefault(); setCurrentTime(t => Math.max(0, t - (e.shiftKey?1:5))); return; }
      if (e.code === 'ArrowRight') { e.preventDefault(); setCurrentTime(t => Math.min(project.duration, t + (e.shiftKey?1:5))); return; }
      if (e.key === 'Escape') { e.preventDefault(); setShowShortcuts(false); setSelectedClipId(null); setSelectedClipIds([]); return; }
      if (e.key === 'n' || e.key === 'N') { addLyricAtPlayhead(); return; }
      if (e.key === 'z' && (e.ctrlKey||e.metaKey)) { e.preventDefault(); undo(); return; }
      if ((e.key === 'y' && (e.ctrlKey||e.metaKey)) || (e.key === 'z' && (e.ctrlKey||e.metaKey) && e.shiftKey)) { e.preventDefault(); redo(); return; }
      if (e.key === 's' && (e.ctrlKey||e.metaKey)) { e.preventDefault(); save(); return; }
      if (e.key === 'd' && (e.ctrlKey||e.metaKey)) {
        e.preventDefault();
        const ids = selectedClipIds.length ? selectedClipIds : (selectedClipId ? [selectedClipId] : []);
        triggerDuplicate(ids);
        return;
      }
      if ((e.key === 's' || e.key === 'S') && !e.ctrlKey && !e.metaKey) {
            e.preventDefault();
            splitSelectedAtPlayhead();
            return;
          }
      if (e.key === 'Delete' || e.key === 'Backspace') {
        const ids = selectedClipIds.length ? selectedClipIds : (selectedClipId ? [selectedClipId] : []);
        triggerDelete(ids);
        return;
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [project, currentTime, selectedClipId, selectedClipIds, undo, redo, triggerDelete, triggerDuplicate]);

  function applyDefaultLyricsStyle() {
    updateProject(p => applyLyricDefaultsToAll(p, true));
    setStatus('Default lyric style applied ✓');
  }

  function splitSelectedAtPlayhead() {
    const clipId = selectedClipId;
    if (!clipId) return;

    const found = findClip(project, clipId);
    if (!found) return;

    const pieces = splitClipAtTime(found.clip, currentTime);
    if (!pieces) return;

    const clips = found.track.clips
      .filter(c => c.id !== found.clip.id)
      .concat(pieces.left, pieces.right)
      .sort((a, b) => Number(a.start || 0) - Number(b.start || 0));

    updateProject(p => replaceClips(p, found.track.id, clips));
    setSelectedClipId(pieces.right.id);
    setSelectedClipIds([pieces.right.id]);
    setStatus(`${found.clip.type === 'audio' ? 'Audio' : 'Clip'} split ✓`);
  }

  function addLyricAtPlayhead() {
    const track = getTrack(project, 'lyrics');
    const clips = track?.clips || [];
    const newClip = {
      id: uid('lyric'), type: 'text',
      start: +currentTime.toFixed(3),
      end:   +Math.min(project.duration, currentTime+2.5).toFixed(3),
      text: 'New lyric line',
      x: project.width/2, y: project.height/2,
      ...LYRIC_DEFAULT_STYLE,
      visible: true, locked: false,
    };
    updateProject(p => replaceClips(p, 'lyrics', [...clips, newClip].sort((a,b)=>a.start-b.start)));
    setSelectedClipId(newClip.id);
    setSelectedClipIds([newClip.id]);
  }

  async function save() {
    setStatus('Saving…'); setError('');
    try { await api.saveEditor(projectId, project); setStatus('Saved ✓'); }
    catch(e) { setError(e.message); setStatus(''); }
  }

  function render() {
    setStatus('Starting render…'); setError(''); setRenderResult(null); setRenderJob(null);
    api.startRender(projectId, project)
      .then(started => {
        setRenderJob({ id: started.jobId, status: 'queued', progress: 0, message: 'Queued' });
        
        if (esRef.current) esRef.current.close();
        
        esRef.current = api.streamJob(started.jobId, 
          (job) => {
            setRenderJob(job);
            if (job.status === 'completed') { setRenderResult(job.result); setStatus('Render complete ✓'); esRef.current = null; }
            if (job.status === 'failed')    { setError(typeof job.error === 'string' ? job.error : JSON.stringify(job.error, null, 2)); setStatus('Render failed'); esRef.current = null; }
          },
          () => { setError('Lost connection to render daemon'); setStatus('Render aborted'); esRef.current = null; }
        );
      })
      .catch(e => { setError(e.message); setStatus('Render failed'); });
  }

  async function reloadLyrics() {
    if (!confirm('Reload synced lyrics from VerseLock? This replaces current lyric clips but keeps the first clip style.')) return;
    setStatus('Reloading lyrics…'); setError('');
    try {
      const data = await api.reloadLyrics(projectId, true);
      updateProject(data.project);
      setSelectedClipId(null); setSelectedClipIds([]);
      setStatus(`Reloaded ${data.lineCount} lyric lines ✓`);
    } catch(e) { setError(e.message); setStatus('Reload failed'); }
  }

  async function scheduleUpload() {
    setStatus('Saving upload schedule…'); setError('');
    try {
      const iso = publishAt ? new Date(publishAt).toISOString() : null;
      await api.scheduleUpload(projectId, { privacy: uploadPrivacy, publish_at: iso, video_path: renderResult?.output || 'renders/final_lyrics_video.mp4', start_upload: false });
      setStatus('Upload schedule saved ✓');
    } catch(e) { setError(e.message); setStatus('Schedule failed'); }
  }

  useEffect(() => {
    if (!status) return;
    const t = setTimeout(() => setStatus(''), 3500);
    return () => clearTimeout(t);
  }, [status]);

  return (
    <div className="editorApp">
      <header className="topbar">
        <div className="brand" onClick={onBack} title="Back to projects">← EchoForge</div>
        <div className="topDivider" />
        <div className="projectName">{project.title||projectId}<span>{project.artist}</span></div>
        <div className="topDivider" />
        <button className="ghost icon-btn" onClick={undo} disabled={!canUndo} title="Undo (Ctrl+Z)">↩</button>
        <button className="ghost icon-btn" onClick={redo} disabled={!canRedo} title="Redo (Ctrl+Y)">↪</button>
        <div className="topDivider" />
        <button className={`ghost icon-btn ${snap?'active':''}`} onClick={() => setSnap(s=>!s)} title="Snap to grid">⊞</button>
        <div className="topSpacer" />
        <div className="topActions">
          <button className="ghost icon-btn" onClick={() => setShowShortcuts(true)} title="Keyboard shortcuts">⌨</button>
          <button onClick={applyDefaultLyricsStyle} title="Set all lyrics to Bernier, 50px, black, centered">Aa Default Lyrics</button>
          <button onClick={reloadLyrics} title="Reload timed lyrics from VerseLock sync output">↻ Reload Lyrics</button>
          <select className="topSelect" value={uploadPrivacy} onChange={e => setUploadPrivacy(e.target.value)} title="Upload privacy">
            <option value="private">Private</option>
            <option value="unlisted">Unlisted</option>
            <option value="public">Public</option>
            <option value="scheduled">Scheduled</option>
          </select>
          <input className="publishAtInput" type="datetime-local" value={publishAt} onChange={e => setPublishAt(e.target.value)} title="Publish at" />
          <button onClick={scheduleUpload} title="Save TubeHarbor upload schedule">🗓 Schedule</button>
          <button onClick={save} title="Ctrl+S">💾 Save</button>
          <button className="primary" onClick={render} title="Render final MP4">⚡ Render MP4</button>
        </div>
      </header>

      {status && <div className="toast">{status}</div>}
      {error  && <div className="toast errorToast">{error}</div>}
      {renderJob && renderJob.status !== 'completed' && renderJob.status !== 'failed' && (
        <div className="toast progressToast">
          {renderJob.message || 'Rendering'} · {Math.round(renderJob.progress || 0)}%
          <div className="progressBar"><span style={{width:`${Math.round(renderJob.progress || 0)}%`}} /></div>
        </div>
      )}
      {renderResult?.output && (
        <div className="toast successToast">
          ✓ {renderResult.absoluteOutput}
          <a href={api.downloadUrl(projectId, renderResult.output)} target="_blank" rel="noreferrer">Download</a>
        </div>
      )}

      <div className="editorBody">
        <div className="editorMid">
          <div className="centerCol">
            <PreviewCanvas
              project={project} projectId={projectId}
              currentTime={currentTime} selectedClipId={selectedClipId} selectedClipIds={selectedClipIds}
              setSelectedClipId={setSelectedClipId} setSelectedClipIds={setSelectedClipIds} updateProject={updateProject}
              playing={playing} setPlaying={setPlaying}
            />
            <Transport
              project={project} projectId={projectId}
              currentTime={currentTime} setCurrentTime={setCurrentTime}
              playing={playing} setPlaying={setPlaying}
            />
          </div>
          <PropertiesPanel
            project={project} selectedClipId={selectedClipId} selectedClipIds={selectedClipIds}
            updateProject={updateProject} triggerDelete={triggerDelete} triggerDuplicate={triggerDuplicate}
          />
        </div>

        <Timeline
          project={project} currentTime={currentTime} setCurrentTime={setCurrentTime}
          selectedClipId={selectedClipId} selectedClipIds={selectedClipIds} setSelectedClipId={setSelectedClipId} setSelectedClipIds={setSelectedClipIds}
          updateProject={updateProject} onAddLyric={addLyricAtPlayhead} snap={snap}
          triggerDelete={triggerDelete} triggerDuplicate={triggerDuplicate}
        />
      </div>

      {showShortcuts && <ShortcutsOverlay onClose={() => setShowShortcuts(false)} />}
    </div>
  );
}

/* ============================================================
   APP ROOT
   ============================================================ */
function App() {
  const [opened, setOpened] = useState(null);
  if (!opened) return <ProjectPicker onOpen={(id, project) => setOpened({ id, project })} />;
  return <Editor projectId={opened.id} initialProject={opened.project} onBack={() => setOpened(null)} />;
}

createRoot(document.getElementById('root')).render(<App />);