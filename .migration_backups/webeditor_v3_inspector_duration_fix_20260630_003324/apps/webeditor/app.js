const $ = (id) => document.getElementById(id);

let project = null;
let selectedClipIds = new Set();
let history = [];
let redoStack = [];
let pxPerSec = 12;
let dragState = null;
let isScrubbing = false;
let historyOpen = false;
let rafPending = false;

let playheadTime = 0;
let transportPlaying = false;
let playbackStartedAt = 0;
let playbackPlayheadAt = 0;
let transportRaf = null;
let activeAudioClipId = null;
let currentAudioAsset = null;

const els = {
  title: $("projectTitle"),
  duration: $("infoDuration"),
  selected: $("infoSelected"),
  selectionStatus: $("selectionStatus"),
  fontStatus: $("fontStatus"),
  viewerShell: $("viewerShell"),
  viewer: $("viewer"),
  bg: $("backgroundImg"),
  lyric: $("lyricOverlay"),
  selectedBox: $("selectedBox"),
  audio: $("audio"),
  play: $("btnPlay"),
  seek: $("masterSeek"),
  time: $("timeReadout"),
  status: $("statusText"),
  ruler: $("ruler"),
  timelineContent: $("timelineContent"),
  tracks: $("tracks"),
  trackLabels: $("trackLabels"),
  tracksViewport: $("tracksViewport"),
  playhead: $("playhead"),
  zoom: $("zoomSlider"),
  clipText: $("clipText"),
  clipStart: $("clipStart"),
  clipEnd: $("clipEnd"),
  clipX: $("clipX"),
  clipY: $("clipY"),
  clipWidth: $("clipWidth"),
  fontSize: $("fontSize"),
  fontFamily: $("fontFamily"),
  fontColor: $("fontColor"),
};

function mediaUrl(rel) {
  if (!rel) return "";
  return "/media/" + rel.replaceAll("\\", "/").replace(/^\/+/, "");
}

function fmtTime(t) {
  t = Math.max(0, Number(t) || 0);
  const m = Math.floor(t / 60);
  const s = Math.floor(t % 60);
  const ms = Math.floor((t - Math.floor(t)) * 1000);
  return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}.${String(ms).padStart(3, "0")}`;
}

function allTracks() { return project?.tracks || []; }
function allClips() { return allTracks().flatMap((track) => (track.clips || []).map((clip) => ({ track, clip }))); }
function textClips() { return allClips().filter(({ clip }) => clip.type === "text").map(({ clip }) => clip); }
function imageClips() { return allClips().filter(({ clip }) => clip.type === "image").map(({ clip }) => clip); }
function audioClips() { return allClips().filter(({ clip }) => clip.type === "audio").map(({ clip }) => clip); }
function findClip(id) { return allClips().find(({ clip }) => clip.id === id)?.clip || null; }
function findTrackOfClip(id) { return allClips().find(({ clip }) => clip.id === id)?.track || null; }
function selectedClips() { return [...selectedClipIds].map((id) => findClip(id)).filter(Boolean); }
function selectedTextClips() { return selectedClips().filter((c) => c.type === "text"); }
function primaryClip() { return findClip([...selectedClipIds][0]); }

function computedDuration() {
  const maxClipEnd = Math.max(0, ...allClips().map(({ clip }) => Number(clip.end) || 0));
  const fallback = Number(project?.project?.duration || 0);
  return Math.max(maxClipEnd, fallback, 0.1);
}
function duration() { return computedDuration(); }
function updateProjectDuration() {
  if (project?.project) project.project.duration = Number(duration().toFixed(3));
  if (els.duration) els.duration.textContent = fmtTime(duration());
}

function setStatus(text) { els.status.textContent = text; }

function beginHistory() {
  if (historyOpen || !project) return;
  history.push(JSON.stringify(project));
  if (history.length > 100) history.shift();
  redoStack = [];
  historyOpen = true;
}
function closeHistory() { historyOpen = false; updateProjectDuration(); }
function pushHistoryOnce() { beginHistory(); closeHistory(); }

function canvasToViewer(x, y) {
  const rect = els.viewer.getBoundingClientRect();
  const c = project.canvas || { width: 1920, height: 1080 };
  return { x: (x / c.width) * rect.width, y: (y / c.height) * rect.height };
}

function timelineNow() { return playheadTime; }
function activeClipOfType(type, t = timelineNow()) {
  return allClips().map(({ clip }) => clip).find((clip) => clip.type === type && t >= clip.start && t < clip.end) || null;
}
function activeBackgroundClip(t = timelineNow()) { return activeClipOfType("image", t); }
function activeAudioClip(t = timelineNow()) { return activeClipOfType("audio", t); }

function activeDisplayClip() {
  const t = timelineNow();
  const active = textClips().find((clip) => t >= clip.start && t < clip.end) || null;
  if (active) return active;
  const selected = primaryClip();
  if (!transportPlaying && selected && selected.type === "text") return selected;
  return null;
}

function applyBackground() {
  const bgClip = activeBackgroundClip();
  if (!bgClip || !bgClip.asset) {
    els.bg.removeAttribute("src");
    els.bg.style.display = "none";
    return;
  }
  const next = mediaUrl(bgClip.asset);
  if (els.bg.getAttribute("src") !== next) els.bg.src = next;
  els.bg.style.display = "block";
  els.bg.style.opacity = String(bgClip.opacity ?? 1);
}

function applyPreview() {
  if (!project) return;
  applyBackground();
  const clip = activeDisplayClip();
  if (!clip || clip.type !== "text") {
    els.lyric.textContent = "";
    els.selectedBox.classList.add("hidden");
    return;
  }
  const style = clip.style || {};
  els.lyric.textContent = clip.text || "";
  els.lyric.style.left = `${(clip.x / project.canvas.width) * 100}%`;
  els.lyric.style.top = `${(clip.y / project.canvas.height) * 100}%`;
  els.lyric.style.width = `${((clip.width || 1500) / project.canvas.width) * 100}%`;
  els.lyric.style.fontFamily = style.fontFamily || "Bernier";
  els.lyric.style.fontSize = `${((style.fontSize || 50) / project.canvas.height) * els.viewer.clientHeight}px`;
  els.lyric.style.color = style.color || "#000000";
  els.lyric.style.opacity = style.opacity ?? 1;
  els.lyric.style.textAlign = style.align || "center";
  els.lyric.style.fontWeight = style.bold ? "800" : "400";
  els.lyric.style.fontStyle = style.italic ? "italic" : "normal";
  els.lyric.classList.toggle("active-selected", selectedClipIds.has(clip.id));

  if (selectedClipIds.has(clip.id)) {
    const p = canvasToViewer(clip.x, clip.y);
    const w = ((clip.width || 1500) / project.canvas.width) * els.viewer.clientWidth;
    const h = Math.max(40, ((clip.height || 140) / project.canvas.height) * els.viewer.clientHeight);
    els.selectedBox.classList.remove("hidden");
    els.selectedBox.style.left = `${p.x - w / 2}px`;
    els.selectedBox.style.top = `${p.y - h / 2}px`;
    els.selectedBox.style.width = `${w}px`;
    els.selectedBox.style.height = `${h}px`;
  } else {
    els.selectedBox.classList.add("hidden");
  }
}

function renderRuler(width) {
  els.ruler.style.width = `${width}px`;
  els.ruler.innerHTML = "";
  const d = duration();
  const step = pxPerSec < 8 ? 10 : pxPerSec < 18 ? 5 : 2;
  for (let t = 0; t <= d + 0.01; t += step) {
    const tick = document.createElement("div");
    tick.className = "tick";
    tick.style.left = `${t * pxPerSec}px`;
    const label = document.createElement("div");
    label.className = "tick-label";
    label.style.left = `${t * pxPerSec}px`;
    label.textContent = fmtTime(t).slice(0, 5);
    els.ruler.appendChild(tick);
    els.ruler.appendChild(label);
  }
}

function clipEl(id) { return els.tracks.querySelector(`[data-clip-id="${CSS.escape(id)}"]`); }

function updateSelectionVisuals() {
  document.querySelectorAll(".clip").forEach((el) => {
    const selected = selectedClipIds.has(el.dataset.clipId);
    el.classList.toggle("selected", selected && selectedClipIds.size === 1);
    el.classList.toggle("multi-selected", selected && selectedClipIds.size > 1);
  });
  const count = selectedClipIds.size;
  els.selectionStatus.textContent = `${count} selected`;
  const p = primaryClip();
  els.selected.textContent = count === 0 ? "No clip selected" : count === 1 ? `${p?.name || p?.id || "Clip"}` : `${count} clips selected`;
}

function renderTimeline() {
  if (!project) return;
  updateProjectDuration();
  const d = duration();
  const width = Math.max(1000, d * pxPerSec + 80);
  els.timelineContent.style.width = `${width}px`;
  els.tracks.style.width = `${width}px`;
  els.trackLabels.innerHTML = "";
  els.tracks.innerHTML = "";

  allTracks().forEach((track) => {
    const label = document.createElement("div");
    label.className = "track-label";
    label.textContent = track.name || track.id;
    els.trackLabels.appendChild(label);

    const row = document.createElement("div");
    row.className = "track-row";
    row.dataset.trackId = track.id;
    row.style.width = `${width}px`;

    (track.clips || []).forEach((clip) => {
      const el = document.createElement("div");
      el.className = `clip ${clip.type}`;
      el.dataset.clipId = clip.id;
      el.style.left = `${clip.start * pxPerSec}px`;
      el.style.width = `${Math.max(10, (clip.end - clip.start) * pxPerSec)}px`;

      const left = document.createElement("div");
      left.className = "handle left";
      left.dataset.handle = "left";
      const right = document.createElement("div");
      right.className = "handle right";
      right.dataset.handle = "right";
      const title = document.createElement("div");
      title.className = "clip-title";
      title.textContent = clip.type === "text" ? (clip.text || clip.name) : (clip.name || clip.type);
      el.append(left, title, right);

      el.addEventListener("pointerdown", (ev) => {
        ev.preventDefault();
        ev.stopPropagation();
        handleClipPointerDown(ev, clip, el);
      });
      row.appendChild(el);
    });

    row.addEventListener("pointerdown", (ev) => {
      if (ev.target !== row) return;
      const t = clientXToTimelineSeconds(ev.clientX);
      seekTo(t);
      selectedClipIds.clear();
      updateSelectionVisuals();
      syncInspectorFromSelection();
      applyPreview();
    });
    els.tracks.appendChild(row);
  });

  renderRuler(width);
  updateSelectionVisuals();
  updatePlayhead();
}

function clientXToTimelineSeconds(clientX) {
  const rect = els.timelineContent.getBoundingClientRect();
  return (clientX - rect.left) / pxPerSec;
}

function handleClipPointerDown(ev, clip, el) {
  const ctrl = ev.ctrlKey || ev.metaKey;
  if (ctrl) {
    if (selectedClipIds.has(clip.id)) selectedClipIds.delete(clip.id);
    else selectedClipIds.add(clip.id);
  } else if (!selectedClipIds.has(clip.id)) {
    selectedClipIds.clear();
    selectedClipIds.add(clip.id);
  }
  updateSelectionVisuals();
  syncInspectorFromSelection();
  applyPreview();

  const handle = ev.target?.dataset?.handle || null;
  beginHistory();
  const movingIds = selectedClipIds.has(clip.id) ? [...selectedClipIds] : [clip.id];
  dragState = {
    mode: handle ? `resize-${handle}` : "move-time",
    clipId: clip.id,
    movingIds,
    startX: ev.clientX,
    originals: movingIds.map((id) => {
      const c = findClip(id);
      return { id, start: c.start, end: c.end, sourceStart: c.sourceStart ?? 0 };
    }),
  };
  el.setPointerCapture(ev.pointerId);
}

function updateClipDomPosition(clip) {
  const el = clipEl(clip.id);
  if (!el) return;
  el.style.left = `${clip.start * pxPerSec}px`;
  el.style.width = `${Math.max(10, (clip.end - clip.start) * pxPerSec)}px`;
  const title = el.querySelector(".clip-title");
  if (title) title.textContent = clip.type === "text" ? (clip.text || clip.name) : (clip.name || clip.type);
}

function updatePlayhead() {
  const t = timelineNow();
  els.playhead.style.left = `${t * pxPerSec}px`;
  const d = duration();
  els.time.textContent = `${fmtTime(t)} / ${fmtTime(d)}`;
  if (!isScrubbing) els.seek.value = String(d ? Math.round((t / d) * 10000) : 0);
  applyPreview();
}

function requestPlayheadUpdate() {
  if (rafPending) return;
  rafPending = true;
  requestAnimationFrame(() => {
    rafPending = false;
    updatePlayhead();
  });
}

function selectAllLyrics() {
  selectedClipIds = new Set(textClips().map((c) => c.id));
  updateSelectionVisuals();
  syncInspectorFromSelection();
  applyPreview();
  setStatus(`Selected ${selectedClipIds.size} lyric clips`);
}

function syncInspectorFromSelection() {
  const selected = selectedTextClips();
  const primary = selected[0];
  const disabled = selected.length === 0;
  [els.clipText, els.clipStart, els.clipEnd, els.clipX, els.clipY, els.clipWidth, els.fontSize, els.fontFamily, els.fontColor].forEach((el) => { el.disabled = disabled; });
  if (disabled) {
    els.clipText.value = "";
    els.clipStart.value = "";
    els.clipEnd.value = "";
    els.clipX.value = "";
    els.clipY.value = "";
    els.clipWidth.value = "";
    els.fontSize.value = "";
    return;
  }
  const st = primary.style || {};
  els.clipText.disabled = selected.length !== 1;
  els.clipText.placeholder = selected.length === 1 ? "" : `${selected.length} clips selected`;
  els.clipText.value = selected.length === 1 ? (primary.text || "") : "";
  els.clipStart.value = primary.start ?? 0;
  els.clipEnd.value = primary.end ?? 0;
  els.clipX.value = primary.x ?? 960;
  els.clipY.value = primary.y ?? 540;
  els.clipWidth.value = primary.width ?? 1500;
  els.fontSize.value = st.fontSize ?? 50;
  els.fontFamily.value = st.fontFamily ?? "Bernier";
  els.fontColor.value = st.color ?? "#000000";
  updateSelectionVisuals();
}

function applyInspectorLive(field) {
  const selected = selectedTextClips();
  if (!selected.length) return;
  beginHistory();

  const primary = selected[0];
  const styleFields = new Set(["fontSize", "fontFamily", "fontColor", "clipX", "clipY", "clipWidth"]);
  const targets = styleFields.has(field) ? selected : [primary];

  targets.forEach((clip) => {
    if (field === "clipText" && selected.length === 1) clip.text = els.clipText.value;
    if (field === "clipStart") clip.start = Math.max(0, Number(els.clipStart.value) || 0);
    if (field === "clipEnd") clip.end = Math.max(clip.start + 0.1, Number(els.clipEnd.value) || clip.start + 1);
    if (field === "clipX") clip.x = Number(els.clipX.value) || 960;
    if (field === "clipY") clip.y = Number(els.clipY.value) || 540;
    if (field === "clipWidth") clip.width = Math.max(60, Number(els.clipWidth.value) || 1500);
    clip.style = clip.style || {};
    if (field === "fontSize") clip.style.fontSize = Math.max(5, Number(els.fontSize.value) || 50);
    if (field === "fontFamily") clip.style.fontFamily = els.fontFamily.value || "Bernier";
    if (field === "fontColor") clip.style.color = els.fontColor.value || "#000000";
    updateClipDomPosition(clip);
  });

  updateProjectDuration();
  renderRuler(Math.max(1000, duration() * pxPerSec + 80));
  updatePlayhead();
  applyPreview();
  setStatus(selected.length > 1 ? `Edited ${selected.length} selected lyric clips` : "Edited selected clip");
}

function routeAudioForTimeline(t, force = false) {
  const clip = activeAudioClip(t);
  if (!clip || !clip.asset) {
    activeAudioClipId = null;
    els.audio.pause();
    els.audio.muted = true;
    return;
  }
  const nextAsset = mediaUrl(clip.asset);
  if (currentAudioAsset !== nextAsset) {
    currentAudioAsset = nextAsset;
    els.audio.src = nextAsset;
    els.audio.load();
    force = true;
  }
  els.audio.muted = false;
  els.audio.volume = Math.max(0, Math.min(1, Number(clip.volume ?? 1)));
  const sourceStart = Number(clip.sourceStart || 0);
  const sourceTime = Math.max(0, sourceStart + (t - clip.start));
  if (force || activeAudioClipId !== clip.id || Math.abs((els.audio.currentTime || 0) - sourceTime) > 0.35) {
    try { els.audio.currentTime = sourceTime; } catch (_) {}
  }
  activeAudioClipId = clip.id;
  if (transportPlaying && els.audio.paused) {
    els.audio.play().catch((err) => setStatus(`Audio play failed: ${err.message}`));
  }
}

function transportTick() {
  if (!transportPlaying) return;
  const elapsed = (performance.now() - playbackStartedAt) / 1000;
  playheadTime = playbackPlayheadAt + elapsed;
  if (playheadTime >= duration()) {
    playheadTime = duration();
    stopTransport();
    updatePlayhead();
    return;
  }
  routeAudioForTimeline(playheadTime, false);
  updatePlayhead();
  transportRaf = requestAnimationFrame(transportTick);
}

function stopTransport() {
  transportPlaying = false;
  if (transportRaf) cancelAnimationFrame(transportRaf);
  transportRaf = null;
  els.audio.pause();
  els.play.textContent = "▶";
}

function seekTo(t) {
  playheadTime = Math.max(0, Math.min(duration(), Number(t) || 0));
  if (transportPlaying) {
    playbackStartedAt = performance.now();
    playbackPlayheadAt = playheadTime;
  }
  routeAudioForTimeline(playheadTime, true);
  requestPlayheadUpdate();
}

function seekBy(delta) { seekTo(timelineNow() + delta); }

function togglePlay() {
  if (!transportPlaying) {
    if (playheadTime >= duration() - 0.01) playheadTime = 0;
    transportPlaying = true;
    playbackStartedAt = performance.now();
    playbackPlayheadAt = playheadTime;
    els.play.textContent = "⏸";
    routeAudioForTimeline(playheadTime, true);
    transportRaf = requestAnimationFrame(transportTick);
  } else {
    stopTransport();
  }
}

function splitSelectedAtPlayhead() {
  const clip = primaryClip();
  const track = clip ? findTrackOfClip(clip.id) : null;
  if (!clip || !track) return setStatus("Select a clip first");
  const t = timelineNow();
  if (t <= clip.start + 0.1 || t >= clip.end - 0.1) return setStatus("Playhead must be inside selected clip");
  pushHistoryOnce();
  const oldEnd = clip.end;
  clip.end = Number(t.toFixed(3));
  const copy = JSON.parse(JSON.stringify(clip));
  const prefix = clip.type === "audio" ? "audio" : clip.type === "image" ? "background" : "lyric";
  copy.id = `${prefix}_${Date.now()}`;
  copy.name = `${clip.name || "Clip"} split`;
  copy.start = Number(t.toFixed(3));
  copy.end = oldEnd;
  if (clip.type === "audio") {
    copy.sourceStart = Number(((clip.sourceStart || 0) + (t - clip.start)).toFixed(3));
  }
  const idx = track.clips.findIndex((c) => c.id === clip.id);
  track.clips.splice(idx + 1, 0, copy);
  selectedClipIds = new Set([copy.id]);
  renderTimeline();
  syncInspectorFromSelection();
  setStatus("Split clip");
}

function deleteSelected() {
  if (!selectedClipIds.size) return;
  pushHistoryOnce();
  const ids = new Set(selectedClipIds);
  allTracks().forEach((track) => { track.clips = (track.clips || []).filter((clip) => !ids.has(clip.id)); });
  selectedClipIds.clear();
  updateProjectDuration();
  renderTimeline();
  seekTo(Math.min(playheadTime, duration()));
  syncInspectorFromSelection();
  applyPreview();
  setStatus(`Deleted ${ids.size} clip(s)`);
}

function addTextClip() {
  const lyricsTrack = allTracks().find((t) => t.type === "text") || allTracks()[1];
  if (!lyricsTrack) return;
  pushHistoryOnce();
  const t = timelineNow();
  const clip = {
    id: `lyric_${Date.now()}`,
    type: "text",
    name: "New Text",
    start: Number(t.toFixed(3)),
    end: Number(Math.max(t + 3, t + 0.5).toFixed(3)),
    text: "New lyric text",
    x: 960,
    y: 540,
    width: 1500,
    height: 140,
    rotation: 0,
    style: { fontFamily: "Bernier", fontSize: 50, color: "#000000", align: "center", opacity: 1 },
  };
  lyricsTrack.clips.push(clip);
  lyricsTrack.clips.sort((a, b) => a.start - b.start);
  selectedClipIds = new Set([clip.id]);
  renderTimeline();
  syncInspectorFromSelection();
  seekTo(clip.start);
  setStatus("Added text clip");
}

function zoomBy(delta) {
  pxPerSec = Math.max(4, Math.min(36, pxPerSec + delta));
  els.zoom.value = String(pxPerSec);
  renderTimeline();
  setStatus(`Zoom ${pxPerSec}px/sec`);
}

async function saveProject() {
  closeHistory();
  updateProjectDuration();
  try {
    const res = await fetch("/api/project", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(project),
    });
    const data = await res.json();
    if (!data.ok) throw new Error(data.error || "Save failed");
    setStatus("Saved editor_project.json");
  } catch (err) {
    setStatus(`Save failed: ${err.message}`);
    alert(err.message);
  }
}

function undo() {
  closeHistory();
  if (!history.length) return;
  redoStack.push(JSON.stringify(project));
  project = JSON.parse(history.pop());
  selectedClipIds.clear();
  normalizeProjectDefaults();
  renderAll();
  setStatus("Undo");
}
function redo() {
  closeHistory();
  if (!redoStack.length) return;
  history.push(JSON.stringify(project));
  project = JSON.parse(redoStack.pop());
  selectedClipIds.clear();
  normalizeProjectDefaults();
  renderAll();
  setStatus("Redo");
}

function normalizeProjectDefaults() {
  allClips().forEach(({ clip }) => {
    if (clip.type === "audio" && clip.sourceStart == null) clip.sourceStart = 0;
    if (clip.type === "audio" && !clip.asset && project.assets?.audio) clip.asset = project.assets.audio;
    if (clip.type === "image" && !clip.asset && project.assets?.background) clip.asset = project.assets.background;
  });
  updateProjectDuration();
}

function renderAll() {
  normalizeProjectDefaults();
  els.title.textContent = `${project.project.title || "Untitled"}${project.project.artist ? " — " + project.project.artist : ""}`;
  els.duration.textContent = fmtTime(duration());
  const firstAudio = audioClips().find((c) => c.asset) || null;
  if (firstAudio) {
    currentAudioAsset = mediaUrl(firstAudio.asset);
    els.audio.src = currentAudioAsset;
  } else if (project.assets?.audio) {
    currentAudioAsset = mediaUrl(project.assets.audio);
    els.audio.src = currentAudioAsset;
  }
  renderTimeline();
  syncInspectorFromSelection();
  applyPreview();
  seekTo(Math.min(playheadTime, duration()));
}

function toggleFullscreen() {
  const target = els.viewerShell || els.viewer;
  if (!document.fullscreenElement) {
    target.requestFullscreen?.().then(() => setStatus("Fullscreen preview")).catch((err) => setStatus(`Fullscreen failed: ${err.message}`));
  } else {
    document.exitFullscreen?.();
  }
}

function wireEvents() {
  els.audio.addEventListener("loadedmetadata", () => {
    // Keep project duration based on timeline clips, not raw audio length.
    updateProjectDuration();
    updatePlayhead();
  });
  els.audio.addEventListener("play", () => { if (transportPlaying) els.play.textContent = "⏸"; });
  els.audio.addEventListener("pause", () => { if (!transportPlaying) els.play.textContent = "▶"; });

  $("btnPlay").addEventListener("click", togglePlay);
  $("btnBack").addEventListener("click", () => seekBy(-1));
  $("btnForward").addEventListener("click", () => seekBy(1));
  $("btnStart").addEventListener("click", () => seekTo(0));
  $("btnEnd").addEventListener("click", () => seekTo(duration()));
  $("btnFullscreen").addEventListener("click", toggleFullscreen);

  els.seek.addEventListener("pointerdown", () => { isScrubbing = true; });
  els.seek.addEventListener("input", () => seekTo((Number(els.seek.value) / 10000) * duration()));
  els.seek.addEventListener("pointerup", () => { isScrubbing = false; });

  els.playhead.addEventListener("pointerdown", (ev) => {
    ev.preventDefault();
    ev.stopPropagation();
    dragState = { mode: "scrub-playhead" };
    els.playhead.setPointerCapture?.(ev.pointerId);
  });

  els.timelineContent.addEventListener("pointerdown", (ev) => {
    if (ev.target.closest(".clip") || ev.target.closest(".playhead")) return;
    seekTo(clientXToTimelineSeconds(ev.clientX));
  });
  els.ruler.addEventListener("pointerdown", (ev) => {
    ev.preventDefault();
    dragState = { mode: "scrub-playhead" };
    seekTo(clientXToTimelineSeconds(ev.clientX));
  });
  els.tracksViewport.addEventListener("wheel", (ev) => {
    if (!ev.ctrlKey) return;
    ev.preventDefault();
    zoomBy(ev.deltaY < 0 ? 1 : -1);
  }, { passive: false });

  els.zoom.addEventListener("input", () => {
    pxPerSec = Number(els.zoom.value);
    renderTimeline();
  });

  $("btnSelectAllLyrics").addEventListener("click", selectAllLyrics);
  $("btnSave").addEventListener("click", saveProject);
  $("btnUndo").addEventListener("click", undo);
  $("btnRedo").addEventListener("click", redo);

  const fieldMap = [
    [els.clipText, "clipText"], [els.clipStart, "clipStart"], [els.clipEnd, "clipEnd"],
    [els.clipX, "clipX"], [els.clipY, "clipY"], [els.clipWidth, "clipWidth"],
    [els.fontSize, "fontSize"], [els.fontFamily, "fontFamily"], [els.fontColor, "fontColor"],
  ];
  fieldMap.forEach(([el, name]) => {
    el.addEventListener("input", () => applyInspectorLive(name));
    el.addEventListener("change", () => { applyInspectorLive(name); closeHistory(); });
    el.addEventListener("blur", closeHistory);
  });

  els.lyric.addEventListener("pointerdown", (ev) => {
    const clip = activeDisplayClip();
    if (!clip || clip.type !== "text") return;
    if (!selectedClipIds.has(clip.id)) selectedClipIds = new Set([clip.id]);
    updateSelectionVisuals();
    syncInspectorFromSelection();
    beginHistory();
    dragState = { mode: "move-canvas", clipId: clip.id, dx: ev.clientX, dy: ev.clientY, origX: clip.x, origY: clip.y };
    els.lyric.setPointerCapture(ev.pointerId);
    ev.preventDefault();
  });

  window.addEventListener("pointermove", (ev) => {
    if (!dragState) return;
    if (dragState.mode === "scrub-playhead") {
      seekTo(clientXToTimelineSeconds(ev.clientX));
      return;
    }

    const primary = findClip(dragState.clipId);
    if (!primary) return;

    if (dragState.mode === "move-canvas") {
      const rect = els.viewer.getBoundingClientRect();
      const c = project.canvas;
      primary.x = Math.round(dragState.origX + ((ev.clientX - dragState.dx) / rect.width) * c.width);
      primary.y = Math.round(dragState.origY + ((ev.clientY - dragState.dy) / rect.height) * c.height);
      syncInspectorFromSelection();
      applyPreview();
      return;
    }

    const deltaSec = (ev.clientX - dragState.startX) / pxPerSec;
    if (dragState.mode === "move-time") {
      dragState.originals.forEach((orig) => {
        const clip = findClip(orig.id);
        if (!clip) return;
        const len = orig.end - orig.start;
        const ns = Math.max(0, orig.start + deltaSec);
        const ne = ns + len;
        clip.start = Number(ns.toFixed(3));
        clip.end = Number(ne.toFixed(3));
        updateClipDomPosition(clip);
      });
    }
    if (dragState.mode === "resize-left") {
      primary.start = Number(Math.max(0, Math.min(dragState.originals[0].end - 0.1, dragState.originals[0].start + deltaSec)).toFixed(3));
      if (primary.type === "audio") {
        primary.sourceStart = Number(Math.max(0, (dragState.originals[0].sourceStart || 0) + (primary.start - dragState.originals[0].start)).toFixed(3));
      }
      updateClipDomPosition(primary);
    }
    if (dragState.mode === "resize-right") {
      primary.end = Number(Math.max(dragState.originals[0].start + 0.1, dragState.originals[0].end + deltaSec).toFixed(3));
      updateClipDomPosition(primary);
    }
    updateProjectDuration();
    syncInspectorFromSelection();
    applyPreview();
  });

  window.addEventListener("pointerup", () => {
    if (dragState) {
      dragState = null;
      closeHistory();
      renderTimeline();
      syncInspectorFromSelection();
      routeAudioForTimeline(playheadTime, true);
    }
  });

  document.addEventListener("keydown", (ev) => {
    const tag = (ev.target?.tagName || "").toLowerCase();
    const editing = ["input", "textarea", "select"].includes(tag);

    if ((ev.ctrlKey || ev.metaKey) && ev.key.toLowerCase() === "s") { ev.preventDefault(); saveProject(); return; }
    if ((ev.ctrlKey || ev.metaKey) && ev.key.toLowerCase() === "z") { ev.preventDefault(); undo(); return; }
    if ((ev.ctrlKey || ev.metaKey) && ev.key.toLowerCase() === "y") { ev.preventDefault(); redo(); return; }
    if ((ev.ctrlKey || ev.metaKey) && ev.key.toLowerCase() === "a" && !editing) { ev.preventDefault(); selectAllLyrics(); return; }
    if (editing) return;

    if (ev.code === "Space") { ev.preventDefault(); togglePlay(); }
    if (ev.key === "ArrowLeft") { ev.preventDefault(); seekBy(ev.shiftKey ? -5 : -1); }
    if (ev.key === "ArrowRight") { ev.preventDefault(); seekBy(ev.shiftKey ? 5 : 1); }
    if (ev.key === "Home") { ev.preventDefault(); seekTo(0); }
    if (ev.key === "End") { ev.preventDefault(); seekTo(duration()); }
    if (ev.key === "Delete" || ev.key === "Backspace") { ev.preventDefault(); deleteSelected(); }
    if (ev.key.toLowerCase() === "s") { ev.preventDefault(); splitSelectedAtPlayhead(); }
    if (ev.key.toLowerCase() === "t") { ev.preventDefault(); addTextClip(); }
    if (ev.key.toLowerCase() === "f") { ev.preventDefault(); toggleFullscreen(); }
    if (ev.key === "+" || ev.key === "=") { ev.preventDefault(); zoomBy(1); }
    if (ev.key === "-" || ev.key === "_") { ev.preventDefault(); zoomBy(-1); }
  });

  document.addEventListener("fullscreenchange", () => {
    $("btnFullscreen").textContent = document.fullscreenElement ? "Exit Fullscreen" : "Fullscreen";
    setTimeout(() => applyPreview(), 100);
  });

  document.fonts.ready.then(() => {
    const ok = document.fonts.check("32px Bernier");
    els.fontStatus.textContent = ok ? "Bernier loaded" : "Bernier missing";
  });
}

async function boot() {
  wireEvents();
  const res = await fetch("/api/project");
  project = await res.json();
  if (!project || project.schema !== "echoforge.webeditor.v2") throw new Error("Invalid project schema");
  normalizeProjectDefaults();
  renderAll();
  setStatus("Loaded WebEditor V3 timeline editor");
}

boot().catch((err) => {
  console.error(err);
  setStatus(`Error: ${err.message}`);
  alert(err.message);
});
