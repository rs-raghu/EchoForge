const $ = (id) => document.getElementById(id);

let project = null;
let selectedClipId = null;
let history = [];
let redoStack = [];
let pxPerSec = 10;
let dragState = null;
let isScrubbing = false;

const els = {
  title: $("projectTitle"),
  duration: $("infoDuration"),
  selected: $("infoSelected"),
  fontStatus: $("fontStatus"),
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
  clipList: $("clipList"),
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

function duration() {
  return Number(project?.project?.duration || els.audio.duration || 10);
}

function allTracks() {
  return project?.tracks || [];
}

function allClips() {
  return allTracks().flatMap((track) => (track.clips || []).map((clip) => ({ track, clip })));
}

function textClips() {
  return allClips().filter(({ clip }) => clip.type === "text").map(({ clip }) => clip);
}

function findClip(id = selectedClipId) {
  return allClips().find(({ clip }) => clip.id === id)?.clip || null;
}

function findTrackOfClip(id = selectedClipId) {
  return allClips().find(({ clip }) => clip.id === id)?.track || null;
}

function pushHistory() {
  if (!project) return;
  history.push(JSON.stringify(project));
  if (history.length > 80) history.shift();
  redoStack = [];
}

function setStatus(text) {
  els.status.textContent = text;
}

function canvasToViewer(x, y) {
  const rect = els.viewer.getBoundingClientRect();
  const c = project.canvas || { width: 1920, height: 1080 };
  return {
    x: (x / c.width) * rect.width,
    y: (y / c.height) * rect.height,
  };
}

function activeDisplayClip() {
  return findClip() || textClips().find((clip) => els.audio.currentTime >= clip.start && els.audio.currentTime < clip.end) || null;
}

function applyPreview() {
  if (!project) return;
  const clip = activeDisplayClip();
  if (!clip) {
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
  els.lyric.classList.toggle("active-selected", clip.id === selectedClipId);

  if (clip.id === selectedClipId) {
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

function renderRuler() {
  const d = duration();
  const width = Math.max(900, d * pxPerSec);
  els.ruler.style.width = `${width}px`;
  els.ruler.innerHTML = "";

  const step = pxPerSec < 8 ? 10 : 5;
  for (let t = 0; t <= d; t += step) {
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

function renderTimeline() {
  if (!project) return;
  document.documentElement.style.setProperty("--px-per-sec", `${pxPerSec}px`);
  const d = duration();
  const width = Math.max(900, d * pxPerSec);

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
      el.style.width = `${Math.max(12, (clip.end - clip.start) * pxPerSec)}px`;
      el.classList.toggle("selected", clip.id === selectedClipId);

      const left = document.createElement("div");
      left.className = "handle left";
      left.dataset.handle = "left";
      const right = document.createElement("div");
      right.className = "handle right";
      right.dataset.handle = "right";

      const title = document.createElement("div");
      title.className = "clip-title";
      title.textContent = clip.type === "text" ? (clip.text || clip.name) : (clip.name || clip.type);

      el.appendChild(left);
      el.appendChild(title);
      el.appendChild(right);

      el.addEventListener("pointerdown", (ev) => {
        ev.preventDefault();
        ev.stopPropagation();
        selectClip(clip.id);
        pushHistory();
        const handle = ev.target?.dataset?.handle || null;
        dragState = {
          mode: handle ? `resize-${handle}` : "move-time",
          clipId: clip.id,
          startX: ev.clientX,
          origStart: clip.start,
          origEnd: clip.end,
        };
        el.setPointerCapture(ev.pointerId);
      });

      row.appendChild(el);
    });

    row.addEventListener("click", (ev) => {
      if (ev.target !== row) return;
      const rect = row.getBoundingClientRect();
      const t = (ev.clientX - rect.left + els.tracksViewport.scrollLeft) / pxPerSec;
      seekTo(t);
    });

    els.tracks.appendChild(row);
  });

  renderRuler();
  updatePlayhead();
  renderClipList();
}

function renderClipList() {
  const clips = textClips();
  els.clipList.innerHTML = "";
  clips.forEach((clip) => {
    const item = document.createElement("div");
    item.className = "clip-list-item";
    item.classList.toggle("selected", clip.id === selectedClipId);
    item.textContent = `${fmtTime(clip.start)}  ${clip.text || ""}`;
    item.addEventListener("click", () => {
      selectClip(clip.id);
      seekTo(clip.start);
    });
    els.clipList.appendChild(item);
  });
}

function updatePlayhead() {
  const t = els.audio.currentTime || 0;
  els.playhead.style.left = `${t * pxPerSec}px`;
  const d = duration();
  els.time.textContent = `${fmtTime(t)} / ${fmtTime(d)}`;
  if (!isScrubbing) {
    els.seek.value = String(d ? Math.round((t / d) * 1000) : 0);
  }
  applyPreview();
}

function selectClip(id) {
  selectedClipId = id;
  const clip = findClip();
  els.selected.textContent = clip ? (clip.name || clip.id) : "None";
  syncInspectorFromClip();
  renderTimeline();
  applyPreview();
}

function syncInspectorFromClip() {
  const clip = findClip();
  const disabled = !clip || clip.type !== "text";
  [els.clipText, els.clipStart, els.clipEnd, els.clipX, els.clipY, els.clipWidth, els.fontSize, els.fontFamily, els.fontColor].forEach((el) => {
    el.disabled = disabled;
  });

  if (disabled) {
    els.clipText.value = "";
    return;
  }

  const st = clip.style || {};
  els.clipText.value = clip.text || "";
  els.clipStart.value = clip.start ?? 0;
  els.clipEnd.value = clip.end ?? 0;
  els.clipX.value = clip.x ?? 960;
  els.clipY.value = clip.y ?? 540;
  els.clipWidth.value = clip.width ?? 1500;
  els.fontSize.value = st.fontSize ?? 50;
  els.fontFamily.value = st.fontFamily ?? "Bernier";
  els.fontColor.value = st.color ?? "#000000";
}

function applyInspectorToSelected(push = true) {
  const clip = findClip();
  if (!clip || clip.type !== "text") return;
  if (push) pushHistory();

  clip.text = els.clipText.value;
  clip.start = Math.max(0, Number(els.clipStart.value) || 0);
  clip.end = Math.max(clip.start + 0.1, Number(els.clipEnd.value) || clip.start + 1);
  clip.x = Number(els.clipX.value) || 960;
  clip.y = Number(els.clipY.value) || 540;
  clip.width = Math.max(60, Number(els.clipWidth.value) || 1500);
  clip.style = clip.style || {};
  clip.style.fontSize = Math.max(5, Number(els.fontSize.value) || 50);
  clip.style.fontFamily = els.fontFamily.value || "Bernier";
  clip.style.color = els.fontColor.value || "#000000";

  renderTimeline();
  applyPreview();
  setStatus("Edited selected clip");
}

function applyStyleToAllLyrics() {
  const clip = findClip();
  if (!clip || clip.type !== "text") return;
  pushHistory();

  const style = {
    ...(clip.style || {}),
    fontSize: Math.max(5, Number(els.fontSize.value) || 50),
    fontFamily: els.fontFamily.value || "Bernier",
    color: els.fontColor.value || "#000000",
  };
  const x = Number(els.clipX.value) || clip.x || 960;
  const y = Number(els.clipY.value) || clip.y || 540;
  const width = Math.max(60, Number(els.clipWidth.value) || clip.width || 1500);

  textClips().forEach((c) => {
    c.style = { ...(c.style || {}), ...style };
    c.x = x;
    c.y = y;
    c.width = width;
  });

  renderTimeline();
  applyPreview();
  setStatus("Applied style to all lyric clips");
}

function seekTo(t) {
  const d = duration();
  const next = Math.max(0, Math.min(d, Number(t) || 0));
  els.audio.currentTime = next;
  updatePlayhead();
}

function togglePlay() {
  if (els.audio.paused) {
    els.audio.play();
  } else {
    els.audio.pause();
  }
}

function splitSelectedAtPlayhead() {
  const clip = findClip();
  const track = findTrackOfClip();
  if (!clip || !track) return;
  const t = els.audio.currentTime;
  if (t <= clip.start + 0.1 || t >= clip.end - 0.1) {
    setStatus("Playhead must be inside selected clip");
    return;
  }
  pushHistory();
  const oldEnd = clip.end;
  clip.end = Number(t.toFixed(3));
  const copy = JSON.parse(JSON.stringify(clip));
  copy.id = `lyric_${Date.now()}`;
  copy.name = `${clip.name || "Lyric"} split`;
  copy.start = Number(t.toFixed(3));
  copy.end = oldEnd;
  const idx = track.clips.findIndex((c) => c.id === clip.id);
  track.clips.splice(idx + 1, 0, copy);
  selectedClipId = copy.id;
  renderTimeline();
  syncInspectorFromClip();
  applyPreview();
  setStatus("Clip split");
}

function deleteSelected() {
  if (!selectedClipId) return;
  const track = findTrackOfClip();
  if (!track) return;
  pushHistory();
  track.clips = track.clips.filter((clip) => clip.id !== selectedClipId);
  selectedClipId = null;
  renderTimeline();
  syncInspectorFromClip();
  applyPreview();
  setStatus("Clip deleted");
}

function addTextClip() {
  const lyricsTrack = allTracks().find((t) => t.type === "text") || allTracks()[1];
  if (!lyricsTrack) return;
  pushHistory();
  const t = els.audio.currentTime;
  const clip = {
    id: `lyric_${Date.now()}`,
    type: "text",
    name: "New Text",
    start: Number(t.toFixed(3)),
    end: Number(Math.min(duration(), t + 3).toFixed(3)),
    text: "New lyric text",
    x: 960,
    y: 540,
    width: 1500,
    height: 140,
    rotation: 0,
    style: {
      fontFamily: "Bernier",
      fontSize: 50,
      color: "#000000",
      align: "center",
      opacity: 1,
    },
  };
  lyricsTrack.clips.push(clip);
  lyricsTrack.clips.sort((a, b) => a.start - b.start);
  selectClip(clip.id);
  setStatus("Added text clip");
}

async function saveProject() {
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
  if (!history.length) return;
  redoStack.push(JSON.stringify(project));
  project = JSON.parse(history.pop());
  selectedClipId = null;
  renderAll();
  setStatus("Undo");
}

function redo() {
  if (!redoStack.length) return;
  history.push(JSON.stringify(project));
  project = JSON.parse(redoStack.pop());
  selectedClipId = null;
  renderAll();
  setStatus("Redo");
}

function renderAll() {
  els.title.textContent = `${project.project.title || "Untitled"}${project.project.artist ? " — " + project.project.artist : ""}`;
  els.duration.textContent = fmtTime(duration());
  if (project.assets?.background) els.bg.src = mediaUrl(project.assets.background);
  if (project.assets?.audio) els.audio.src = mediaUrl(project.assets.audio);
  renderTimeline();
  syncInspectorFromClip();
  applyPreview();
}

function wireEvents() {
  els.audio.addEventListener("loadedmetadata", () => {
    if (!project.project.duration || project.project.duration < els.audio.duration) {
      project.project.duration = Number(els.audio.duration.toFixed(3));
    }
    renderTimeline();
    updatePlayhead();
  });

  els.audio.addEventListener("timeupdate", updatePlayhead);
  els.audio.addEventListener("play", () => { els.play.textContent = "⏸"; });
  els.audio.addEventListener("pause", () => { els.play.textContent = "▶"; });

  $("btnPlay").addEventListener("click", togglePlay);
  $("btnBack").addEventListener("click", () => seekTo(els.audio.currentTime - 5));
  $("btnForward").addEventListener("click", () => seekTo(els.audio.currentTime + 5));
  $("btnStart").addEventListener("click", () => seekTo(0));
  $("btnEnd").addEventListener("click", () => seekTo(duration()));

  els.seek.addEventListener("pointerdown", () => { isScrubbing = true; });
  els.seek.addEventListener("input", () => {
    const t = (Number(els.seek.value) / 1000) * duration();
    seekTo(t);
  });
  els.seek.addEventListener("pointerup", () => { isScrubbing = false; });

  els.ruler.addEventListener("click", (ev) => {
    const rect = els.ruler.getBoundingClientRect();
    const t = (ev.clientX - rect.left + els.tracksViewport.scrollLeft) / pxPerSec;
    seekTo(t);
  });

  els.zoom.addEventListener("input", () => {
    pxPerSec = Number(els.zoom.value);
    renderTimeline();
  });

  $("btnApplySelected").addEventListener("click", () => applyInspectorToSelected(true));
  $("btnApplyAll").addEventListener("click", applyStyleToAllLyrics);
  $("btnSplit").addEventListener("click", splitSelectedAtPlayhead);
  $("btnDelete").addEventListener("click", deleteSelected);
  $("btnAddText").addEventListener("click", addTextClip);
  $("btnSave").addEventListener("click", saveProject);
  $("btnUndo").addEventListener("click", undo);
  $("btnRedo").addEventListener("click", redo);

  [els.clipText, els.clipStart, els.clipEnd, els.clipX, els.clipY, els.clipWidth, els.fontSize, els.fontFamily, els.fontColor].forEach((el) => {
    el.addEventListener("change", () => applyInspectorToSelected(true));
  });

  els.lyric.addEventListener("pointerdown", (ev) => {
    const clip = activeDisplayClip();
    if (!clip || clip.type !== "text") return;
    selectClip(clip.id);
    pushHistory();
    dragState = {
      mode: "move-canvas",
      clipId: clip.id,
      dx: ev.clientX,
      dy: ev.clientY,
      origX: clip.x,
      origY: clip.y,
    };
    els.lyric.setPointerCapture(ev.pointerId);
    ev.preventDefault();
  });

  window.addEventListener("pointermove", (ev) => {
    if (!dragState) return;
    const clip = findClip(dragState.clipId);
    if (!clip) return;

    if (dragState.mode === "move-canvas") {
      const rect = els.viewer.getBoundingClientRect();
      const c = project.canvas;
      clip.x = Math.round(dragState.origX + ((ev.clientX - dragState.dx) / rect.width) * c.width);
      clip.y = Math.round(dragState.origY + ((ev.clientY - dragState.dy) / rect.height) * c.height);
      syncInspectorFromClip();
      applyPreview();
      return;
    }

    const deltaSec = (ev.clientX - dragState.startX) / pxPerSec;

    if (dragState.mode === "move-time") {
      const len = dragState.origEnd - dragState.origStart;
      let ns = Math.max(0, dragState.origStart + deltaSec);
      let ne = Math.min(duration(), ns + len);
      if (ne - ns < len) ns = ne - len;
      clip.start = Number(ns.toFixed(3));
      clip.end = Number(ne.toFixed(3));
    }

    if (dragState.mode === "resize-left") {
      clip.start = Number(Math.max(0, Math.min(dragState.origEnd - 0.1, dragState.origStart + deltaSec)).toFixed(3));
    }

    if (dragState.mode === "resize-right") {
      clip.end = Number(Math.min(duration(), Math.max(dragState.origStart + 0.1, dragState.origEnd + deltaSec)).toFixed(3));
    }

    syncInspectorFromClip();
    renderTimeline();
    applyPreview();
  });

  window.addEventListener("pointerup", () => {
    dragState = null;
  });

  document.addEventListener("keydown", (ev) => {
    const tag = (ev.target?.tagName || "").toLowerCase();
    const editing = ["input", "textarea", "select"].includes(tag);
    if (editing) return;

    if (ev.code === "Space") {
      ev.preventDefault();
      togglePlay();
    }
    if (ev.key === "ArrowLeft") {
      ev.preventDefault();
      seekTo(els.audio.currentTime - 5);
    }
    if (ev.key === "ArrowRight") {
      ev.preventDefault();
      seekTo(els.audio.currentTime + 5);
    }
    if (ev.key === "Delete") {
      ev.preventDefault();
      deleteSelected();
    }
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
  if (!project || project.schema !== "echoforge.webeditor.v2") {
    throw new Error("Invalid project schema");
  }
  renderAll();
  setStatus("Loaded WebEditor V2");
}

boot().catch((err) => {
  console.error(err);
  setStatus(`Error: ${err.message}`);
  alert(err.message);
});
