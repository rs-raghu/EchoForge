from __future__ import annotations

import argparse
import json
import mimetypes
import re
import sys
import threading
import webbrowser
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

ROOT_DIR = Path(__file__).resolve().parents[4]


def read_json(path: Path, default: Any = None) -> Any:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return default


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8", newline="\n")


def fnum(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except Exception:
        return default


def resolve_path(project_dir: Path, value: Any) -> Path | None:
    if not value:
        return None
    p = Path(str(value))
    candidates = [p] if p.is_absolute() else [project_dir / p, ROOT_DIR / p]
    for c in candidates:
        if c.exists():
            return c.resolve()
    return candidates[-1].resolve() if candidates else None


def rel_to(base: Path, path: Path | None) -> str:
    if not path:
        return ""
    try:
        return str(path.resolve().relative_to(base.resolve())).replace("\\", "/")
    except Exception:
        try:
            return str(path.resolve().relative_to(ROOT_DIR.resolve())).replace("\\", "/")
        except Exception:
            return str(path).replace("\\", "/")


def first_existing(paths: list[Path]) -> Path | None:
    for p in paths:
        if p.exists():
            return p
    return None


def parse_lrc(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    pat = re.compile(r"\[(\d+):(\d+(?:\.\d+)?)\]\s*(.*)")
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        m = pat.match(line.strip())
        if not m:
            continue
        text = m.group(3).strip()
        if not text:
            continue
        rows.append({"start": int(m.group(1)) * 60 + float(m.group(2)), "text": text})
    rows.sort(key=lambda r: r["start"])
    for i, row in enumerate(rows):
        nxt = rows[i + 1]["start"] if i + 1 < len(rows) else row["start"] + 3.0
        row["end"] = max(row["start"] + 0.4, nxt - 0.05)
    return rows


def normalize_clip(item: dict[str, Any], idx: int, default_style: dict[str, Any]) -> dict[str, Any]:
    style = dict(default_style)
    if isinstance(item.get("style"), dict):
        style.update(item["style"])
    start = fnum(item.get("start") or item.get("start_time") or item.get("time"), 0.0)
    end = fnum(item.get("end") or item.get("end_time"), start + 2.5)
    if end <= start:
        end = start + 1.0
    text = str(item.get("text") or item.get("line") or item.get("lyric") or "").strip()
    return {
        "id": str(item.get("id") or f"lyric_{idx + 1:04d}"),
        "type": "lyric",
        "track": "lyrics",
        "text": text,
        "start": round(start, 3),
        "end": round(end, 3),
        "duration": round(end - start, 3),
        "locked": bool(item.get("locked", False)),
        "visible": bool(item.get("visible", True)),
        "style": style,
    }


def default_lyric_style(source: dict[str, Any] | None = None) -> dict[str, Any]:
    source = source or {}
    pos = source.get("lyric_position") if isinstance(source.get("lyric_position"), dict) else {}
    return {
        "font_family": source.get("lyric_font_family") or source.get("font_family") or "Bernier",
        "font_size": fnum(source.get("lyric_font_size") or source.get("font_size"), 50),
        "fill": source.get("lyric_fill") or source.get("fill") or "#000000",
        "stroke": source.get("lyric_stroke") or source.get("stroke"),
        "stroke_width": fnum(source.get("stroke_width"), 0),
        "align": source.get("align") or "center",
        "x": fnum(pos.get("x") if pos else source.get("x"), 960),
        "y": fnum(pos.get("y") if pos else source.get("y"), 540),
        "anchor": source.get("anchor") or "center",
        "max_width": fnum(source.get("lyric_max_width") or source.get("max_width"), 1320),
        "line_height": fnum(source.get("line_height"), 1.05),
    }


def load_project(project_dir: Path) -> dict[str, Any]:
    editor_dir = project_dir / "editor"
    editor_project = read_json(editor_dir / "editor_project.json", None)
    if not isinstance(editor_project, dict):
        final_lrc = project_dir / "sync" / "final_synced_lyrics.lrc"
        style = default_lyric_style()
        rows = parse_lrc(final_lrc)
        editor_project = {
            "schema_version": 1,
            "stage": "renderer_stage2_webeditor_v2",
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "project_dir": rel_to(ROOT_DIR, project_dir),
            "song_title": project_dir.name,
            "artist": "",
            "canvas": {"width": 1920, "height": 1080, "fps": 30},
            "assets": {
                "audio": rel_to(project_dir, first_existing([project_dir / "audio" / "source_audio.m4a", project_dir / "audio" / "source_audio.mp4"])),
                "background": rel_to(project_dir, first_existing([project_dir / "images" / "video_background.jpg", project_dir / "images" / "background_source.jpg"])),
                "font_bernier": "assets/fonts/Bernier/Bernier-Regular.ttf",
                "final_lrc": "sync/final_synced_lyrics.lrc",
            },
            "defaults": style,
            "clips": [normalize_clip(c, i, style) for i, c in enumerate(rows)],
        }
        write_json(editor_dir / "editor_project.json", editor_project)
    style = default_lyric_style(editor_project.get("defaults") if isinstance(editor_project.get("defaults"), dict) else {})
    raw = editor_project.get("clips") if isinstance(editor_project.get("clips"), list) else []
    editor_project["clips"] = [normalize_clip(c, i, style) for i, c in enumerate(raw) if isinstance(c, dict)]
    editor_project.setdefault("canvas", {"width": 1920, "height": 1080, "fps": 30})
    editor_project.setdefault("assets", {})
    editor_project.setdefault("song_title", editor_project.get("title") or project_dir.name)
    editor_project.setdefault("artist", "")
    return editor_project


HTML = r"""
<!doctype html><html><head><meta charset="utf-8"/><meta name="viewport" content="width=device-width, initial-scale=1"/><title>EchoForge WebEditor</title>
<style>
@font-face{font-family:Bernier;src:url('/media/font') format('truetype');font-display:swap;}
:root{--bg:#0b0d10;--panel:#141820;--panel2:#10131a;--line:#2a303c;--muted:#8d96a8;--text:#eef1f6;--accent:#7aa2ff;--danger:#ff6b6b;--ok:#73e2a7;--clip:#5b7cfa;--clip2:#2f52d9}*{box-sizing:border-box}html,body{height:100%;margin:0;overflow:hidden;background:var(--bg);color:var(--text);font-family:Inter,Segoe UI,Arial,sans-serif}button,input,textarea{font:inherit}button{background:#202635;color:var(--text);border:1px solid #384154;border-radius:8px;padding:8px 10px;cursor:pointer}button:hover{border-color:var(--accent)}button.primary{background:#254edb;border-color:#416bff}#app{height:100%;display:grid;grid-template-rows:42px 1fr 210px}.topbar{display:flex;align-items:center;gap:12px;padding:0 14px;background:#0f1218;border-bottom:1px solid var(--line)}.brand{font-weight:800}.pill{font-size:12px;color:var(--muted);border:1px solid var(--line);padding:4px 8px;border-radius:99px}.grow{flex:1}.ok{color:var(--ok)}.bad{color:var(--danger)}.workspace{display:grid;grid-template-columns:260px 1fr 330px;min-height:0}.panel{background:var(--panel);border-right:1px solid var(--line);min-height:0;overflow:auto}.panel.right{border-right:0;border-left:1px solid var(--line)}.panel h3{font-size:12px;letter-spacing:.12em;color:var(--muted);text-transform:uppercase;margin:14px 14px 8px}.media-card{margin:10px 14px;padding:10px;background:var(--panel2);border:1px solid var(--line);border-radius:10px;font-size:13px}.media-card b{display:block;margin-bottom:4px}.media-path{color:var(--muted);font-size:11px;word-break:break-all}.clip-list{padding:8px 10px}.clip-row{padding:8px 9px;margin:5px 0;border:1px solid transparent;border-radius:8px;background:#10141d;cursor:pointer}.clip-row:hover{border-color:#475064}.clip-row.active{border-color:var(--accent);background:#172344}.clip-time{color:var(--muted);font-size:11px}.clip-text{white-space:nowrap;overflow:hidden;text-overflow:ellipsis;font-size:13px}.viewer-wrap{min-width:0;display:grid;grid-template-rows:1fr 86px;background:#080a0d}.program{display:flex;align-items:center;justify-content:center;min-height:0;padding:18px}.canvas{position:relative;aspect-ratio:16/9;width:min(100%,calc((100vh - 350px)*16/9));max-width:100%;background:#000;box-shadow:0 12px 50px #000a;border:1px solid #222936;overflow:hidden}.canvas img.bg{position:absolute;inset:0;width:100%;height:100%;object-fit:cover;user-select:none}.safe{position:absolute;inset:6%;border:1px dashed rgba(255,255,255,.13);pointer-events:none}.lyric{position:absolute;left:50%;top:50%;transform:translate(-50%,-50%);white-space:pre-wrap;text-align:center;cursor:move;user-select:none;line-height:1.05;max-width:70%;padding:6px 10px;border:1px solid transparent}.lyric.selected{border-color:rgba(122,162,255,.6);background:rgba(122,162,255,.05)}.controls{border-top:1px solid var(--line);background:#10131a;padding:10px 14px;display:grid;grid-template-columns:auto 1fr auto;gap:12px;align-items:center}.transport{display:flex;gap:8px;align-items:center}.timecode{font-family:Consolas,monospace;font-size:13px;color:#dfe6ff;min-width:145px;text-align:center}.seek{width:100%}.status{font-size:12px;color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.timeline{background:#0c0f15;border-top:1px solid var(--line);display:grid;grid-template-rows:26px 1fr;min-height:0}.ruler{position:relative;border-bottom:1px solid var(--line);background:#10131a;overflow:hidden}.ruler-tick{position:absolute;top:0;height:100%;border-left:1px solid #343b4a;color:var(--muted);font-size:10px;padding-left:4px}.tracks{position:relative;overflow:auto}.track{position:relative;height:55px;border-bottom:1px solid #202634}.track-label{position:sticky;left:0;width:110px;height:100%;background:#111722;border-right:1px solid var(--line);display:flex;align-items:center;padding-left:10px;color:var(--muted);z-index:3}.clipbar{position:absolute;top:9px;height:36px;border-radius:8px;background:linear-gradient(180deg,var(--clip),var(--clip2));border:1px solid #89a0ff;color:white;font-size:12px;display:flex;align-items:center;padding:0 8px;overflow:hidden;white-space:nowrap;cursor:pointer;z-index:2}.clipbar.active{outline:2px solid white}.playhead{position:absolute;top:0;bottom:0;width:2px;background:#ff4d6d;z-index:5;pointer-events:none}.playhead:before{content:'';position:absolute;top:0;left:-5px;border-left:6px solid transparent;border-right:6px solid transparent;border-top:8px solid #ff4d6d}.inspector{padding:0 14px 18px}.field{margin:10px 0}.field label{display:block;font-size:11px;text-transform:uppercase;letter-spacing:.08em;color:var(--muted);margin-bottom:5px}.field input,.field textarea{width:100%;background:#0e121a;color:var(--text);border:1px solid #333b4d;border-radius:8px;padding:8px}.row2{display:grid;grid-template-columns:1fr 1fr;gap:8px}.row3{display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px}.hint{font-size:12px;color:var(--muted);line-height:1.4;margin:8px 14px}.hidden-audio{position:absolute;left:-9999px;top:-9999px}
</style></head><body>
<div id="app"><div class="topbar"><div class="brand">EchoForge WebEditor</div><span id="song" class="pill">Loading...</span><span id="fontStatus" class="pill">Font...</span><div class="grow"></div><button id="saveBtn" class="primary">Save</button></div><div class="workspace"><aside class="panel"><h3>Media Bin</h3><div class="media-card"><b>Background</b><div id="bgPath" class="media-path"></div></div><div class="media-card"><b>Audio</b><div id="audioPath" class="media-path"></div></div><h3>Lyrics</h3><div class="hint">Click a clip to select. Click empty timeline to seek.</div><div id="clipList" class="clip-list"></div></aside><main class="viewer-wrap"><section class="program"><div id="canvas" class="canvas"><img id="bg" class="bg" draggable="false"/><div class="safe"></div><div id="lyric" class="lyric selected"></div></div></section><section class="controls"><div class="transport"><button id="playBtn">Play</button><button id="backBtn">−5s</button><button id="fwdBtn">+5s</button></div><input id="seek" class="seek" type="range" min="0" max="1000" step="1" value="0"/><div class="timecode" id="timecode">00:00.000 / 00:00.000</div><div class="status" id="status">Ready</div></section></main><aside class="panel right"><h3>Inspector</h3><div class="inspector"><div class="field"><label>Selected text</label><textarea id="textInput" rows="4"></textarea></div><div class="row2"><div class="field"><label>Start</label><input id="startInput" type="number" step="0.01"/></div><div class="field"><label>End</label><input id="endInput" type="number" step="0.01"/></div></div><div class="row3"><div class="field"><label>Font size</label><input id="fontInput" type="number" step="1"/></div><div class="field"><label>X</label><input id="xInput" type="number" step="1"/></div><div class="field"><label>Y</label><input id="yInput" type="number" step="1"/></div></div><div class="row2"><div class="field"><label>Color</label><input id="colorInput" type="color"/></div><div class="field"><label>Max width</label><input id="widthInput" type="number" step="10"/></div></div><button id="applyBtn">Apply selected</button> <button id="applyAllBtn">Apply style to all clips</button><div class="hint">Drag lyric on monitor. Space = play/pause, arrows = seek.</div></div></aside></div><div class="timeline"><div id="ruler" class="ruler"></div><div id="tracks" class="tracks"><div id="lyricsTrack" class="track"><div class="track-label">Lyrics</div><div id="playhead" class="playhead"></div></div></div></div></div><audio id="audio" class="hidden-audio" preload="metadata"></audio>
<script>
const $=id=>document.getElementById(id);let state=null,selectedIndex=0,duration=1,scale=10,raf=0;const audio=$('audio'),seek=$('seek'),lyric=$('lyric'),canvas=$('canvas'),track=$('lyricsTrack');function log(m,b=false){$('status').textContent=m;$('status').style.color=b?'#ff6b6b':'#8d96a8'}function fmt(t){t=Math.max(0,Number(t)||0);let m=Math.floor(t/60),s=Math.floor(t%60),ms=Math.floor((t%1)*1000);return `${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')}.${String(ms).padStart(3,'0')}`}function clipDuration(){return Math.max(1,...state.clips.map(c=>Number(c.end)||0),audio.duration||0)}function styleOf(c){c.style=c.style||{};return c.style}function activeIndexAt(t){for(let i=0;i<state.clips.length;i++){let c=state.clips[i];if(t>=c.start&&t<c.end)return i}let b=0,d=1e9;state.clips.forEach((c,i)=>{let x=Math.abs((c.start+c.end)/2-t);if(x<d){d=x;b=i}});return b}function drawLyric(){if(!state||!state.clips.length)return;let c=state.clips[selectedIndex],s=styleOf(c);lyric.textContent=c.text||'';lyric.style.fontFamily='Bernier,Impact,sans-serif';lyric.style.fontSize=(Number(s.font_size)||50)+'px';lyric.style.color=s.fill||'#000';lyric.style.maxWidth=((Number(s.max_width)||1320)/state.canvas.width*100)+'%';lyric.style.left=((Number(s.x)||960)/state.canvas.width*100)+'%';lyric.style.top=((Number(s.y)||540)/state.canvas.height*100)+'%';lyric.style.textShadow=s.stroke?`0 0 ${s.stroke_width||2}px ${s.stroke}`:'none'}function fillInspector(){let c=state.clips[selectedIndex],s=styleOf(c);$('textInput').value=c.text||'';$('startInput').value=Number(c.start).toFixed(3);$('endInput').value=Number(c.end).toFixed(3);$('fontInput').value=Math.round(Number(s.font_size)||50);$('xInput').value=Math.round(Number(s.x)||960);$('yInput').value=Math.round(Number(s.y)||540);$('colorInput').value=s.fill||'#000000';$('widthInput').value=Math.round(Number(s.max_width)||1320)}function setSelected(i,go=false){if(!state||!state.clips.length)return;selectedIndex=Math.max(0,Math.min(state.clips.length-1,i));document.querySelectorAll('.clip-row,.clipbar').forEach(e=>e.classList.remove('active'));document.querySelectorAll(`[data-idx="${selectedIndex}"]`).forEach(e=>e.classList.add('active'));fillInspector();drawLyric();if(go)seekTo(state.clips[selectedIndex].start)}function renderClipList(){let box=$('clipList');box.innerHTML='';state.clips.forEach((c,i)=>{let d=document.createElement('div');d.className='clip-row';d.dataset.idx=i;d.innerHTML=`<div class="clip-time">${fmt(c.start)} → ${fmt(c.end)}</div><div class="clip-text"></div>`;d.querySelector('.clip-text').textContent=c.text;d.onclick=()=>setSelected(i,true);box.appendChild(d)})}function renderTimeline(){duration=clipDuration();scale=Math.max(7,Math.min(22,1300/duration));track.style.width=(Math.ceil(duration*scale)+140)+'px';$('ruler').innerHTML='';for(let t=0;t<=duration;t+=10){let r=document.createElement('div');r.className='ruler-tick';r.style.left=(110+t*scale)+'px';r.textContent=fmt(t).slice(0,5);$('ruler').appendChild(r)}document.querySelectorAll('.clipbar').forEach(e=>e.remove());state.clips.forEach((c,i)=>{let b=document.createElement('div');b.className='clipbar';b.dataset.idx=i;b.style.left=(110+c.start*scale)+'px';b.style.width=Math.max(14,(c.end-c.start)*scale)+'px';b.textContent=c.text;b.onclick=e=>{e.stopPropagation();setSelected(i,true)};track.appendChild(b)});$('tracks').onclick=e=>{if(e.target.classList.contains('clipbar'))return;let rect=track.getBoundingClientRect();let x=e.clientX-rect.left+$('tracks').scrollLeft-110;if(x>=0)seekTo(x/scale)};setSelected(selectedIndex,false);updateClock()}function updateClock(){duration=clipDuration();let t=audio.currentTime||0;$('timecode').textContent=`${fmt(t)} / ${fmt(duration)}`;seek.value=duration?Math.round(t/duration*1000):0;$('playhead').style.left=(110+t*scale)+'px';let idx=activeIndexAt(t);if(idx!==selectedIndex&&!['INPUT','TEXTAREA'].includes(document.activeElement.tagName)){selectedIndex=idx;setSelected(idx,false)}}function loop(){updateClock();raf=requestAnimationFrame(loop)}async function ensureReady(){if(audio.readyState>=1)return;await new Promise(res=>{audio.addEventListener('loadedmetadata',res,{once:true});audio.load();setTimeout(res,1200)})}async function seekTo(t){await ensureReady();duration=clipDuration();t=Math.max(0,Math.min(duration-.01,Number(t)||0));try{audio.currentTime=t;log('Seeked to '+fmt(t))}catch(e){log('Seek failed: '+e.message,true)}updateClock()}function seekBy(d){seekTo((audio.currentTime||0)+d)}async function toggle(){await ensureReady();if(audio.paused){await audio.play();$('playBtn').textContent='Pause';loop()}else{audio.pause();$('playBtn').textContent='Play';cancelAnimationFrame(raf)}}function applySelected(){let c=state.clips[selectedIndex],s=styleOf(c);c.text=$('textInput').value;c.start=Number($('startInput').value)||0;c.end=Math.max(c.start+.2,Number($('endInput').value)||c.start+2);c.duration=+(c.end-c.start).toFixed(3);s.font_size=Number($('fontInput').value)||50;s.fill=$('colorInput').value||'#000000';s.x=Number($('xInput').value)||960;s.y=Number($('yInput').value)||540;s.max_width=Number($('widthInput').value)||1320;state.clips.sort((a,b)=>a.start-b.start);selectedIndex=state.clips.indexOf(c);renderClipList();renderTimeline();drawLyric();log('Selected clip updated. Click Save.')}function applyAll(){applySelected();let base={...styleOf(state.clips[selectedIndex])};state.clips.forEach(c=>{c.style={...styleOf(c),font_family:'Bernier',font_size:base.font_size,fill:base.fill,stroke:base.stroke,stroke_width:base.stroke_width,x:base.x,y:base.y,max_width:base.max_width,line_height:base.line_height||1.05,align:'center',anchor:'center'}});renderTimeline();drawLyric();log('Style applied to all clips. Click Save.')}async function save(){applySelected();let r=await fetch('/api/save',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(state)});let j=await r.json();log(j.ok?`Saved ${j.clip_count} clips`:`Save failed: ${j.reason}`,!j.ok)}let dragging=false;function p2c(e){let r=canvas.getBoundingClientRect();return{x:(e.clientX-r.left)/r.width*state.canvas.width,y:(e.clientY-r.top)/r.height*state.canvas.height}}lyric.addEventListener('pointerdown',e=>{dragging=true;lyric.setPointerCapture(e.pointerId);e.preventDefault()});lyric.addEventListener('pointermove',e=>{if(!dragging)return;let p=p2c(e),s=styleOf(state.clips[selectedIndex]);s.x=Math.round(p.x);s.y=Math.round(p.y);$('xInput').value=s.x;$('yInput').value=s.y;drawLyric()});lyric.addEventListener('pointerup',()=>{dragging=false;log('Position changed. Click Save.')});$('playBtn').onclick=toggle;$('backBtn').onclick=()=>seekBy(-5);$('fwdBtn').onclick=()=>seekBy(5);$('applyBtn').onclick=applySelected;$('applyAllBtn').onclick=applyAll;$('saveBtn').onclick=save;seek.addEventListener('input',()=>{if(duration)seekTo((Number(seek.value)/1000)*duration)});audio.addEventListener('loadedmetadata',()=>{duration=clipDuration();renderTimeline();updateClock()});audio.addEventListener('timeupdate',updateClock);audio.addEventListener('pause',()=>{$('playBtn').textContent='Play'});audio.addEventListener('play',()=>{$('playBtn').textContent='Pause'});document.addEventListener('keydown',e=>{let tag=document.activeElement?.tagName?.toLowerCase();if(tag==='input'||tag==='textarea')return;if(e.code==='Space'){e.preventDefault();toggle()}else if(e.code==='ArrowLeft'){e.preventDefault();seekBy(-5)}else if(e.code==='ArrowRight'){e.preventDefault();seekBy(5)}},true);(async()=>{let r=await fetch('/api/project');state=await r.json();$('song').textContent=(state.song_title||state.title||'Untitled')+(state.artist?' — '+state.artist:'');$('bgPath').textContent=state.assets?.background||'';$('audioPath').textContent=state.assets?.audio||'';$('bg').src='/media/background?t='+Date.now();audio.src='/media/audio?t='+Date.now();try{await document.fonts.load('50px Bernier');let ok=[...document.fonts].some(f=>f.family==='Bernier'&&f.status==='loaded');$('fontStatus').innerHTML=ok?'<span class="ok">Bernier loaded</span>':'<span class="bad">Bernier missing</span>'}catch(e){$('fontStatus').innerHTML='<span class="bad">Font failed</span>'}renderClipList();renderTimeline();setSelected(0,false);log('Editor ready. Range seeking enabled.')})().catch(e=>log(e.stack||String(e),true));
</script></body></html>
"""


class App:
    def __init__(self, project_dir: Path):
        self.project_dir = project_dir.resolve()
        self.project = load_project(self.project_dir)

    def refresh(self) -> dict[str, Any]:
        self.project = load_project(self.project_dir)
        return self.project

    def asset(self, name: str) -> Path | None:
        assets = self.project.get("assets", {}) if isinstance(self.project.get("assets"), dict) else {}
        if name == "background":
            return resolve_path(self.project_dir, assets.get("background")) or first_existing([self.project_dir / "images" / "video_background.jpg", self.project_dir / "images" / "background_source.jpg"])
        if name == "audio":
            return resolve_path(self.project_dir, assets.get("audio")) or first_existing([self.project_dir / "audio" / "source_audio.m4a", self.project_dir / "audio" / "source_audio.mp4", self.project_dir / "audio" / "source_audio.mp3"])
        if name == "font":
            return resolve_path(self.project_dir, assets.get("font_bernier")) or first_existing([ROOT_DIR / "assets" / "fonts" / "Bernier" / "Bernier-Regular.ttf"])
        return None

    def save(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, dict) or not isinstance(payload.get("clips"), list):
            return {"ok": False, "reason": "Invalid editor project payload."}
        style = default_lyric_style()
        payload["clips"] = [normalize_clip(c, i, style) for i, c in enumerate(payload["clips"]) if isinstance(c, dict)]
        payload["updated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        payload["stage"] = "renderer_stage2_webeditor_v2"
        editor_dir = self.project_dir / "editor"
        write_json(editor_dir / "editor_project.json", payload)
        write_json(editor_dir / "timeline.json", {"clips": payload["clips"], "updated_at": payload["updated_at"]})
        self.project = payload
        return {"ok": True, "clip_count": len(payload["clips"]), "editor_project": str(editor_dir / "editor_project.json")}


def handler_factory(app: App):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *args: Any) -> None:
            sys.stderr.write("[WebEditor] " + fmt % args + "\n")

        def send_bytes(self, status: int, body: bytes, ctype: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(body)

        def send_json(self, status: int, data: Any) -> None:
            self.send_bytes(status, json.dumps(data, indent=2, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

        def send_file(self, path: Path | None, ctype: str | None = None) -> None:
            if not path or not path.exists():
                self.send_json(404, {"ok": False, "reason": "File not found", "path": str(path)})
                return
            size = path.stat().st_size
            ctype = ctype or mimetypes.guess_type(str(path))[0] or "application/octet-stream"
            range_header = self.headers.get("Range")
            if range_header:
                m = re.match(r"bytes=(\d*)-(\d*)", range_header)
                if m:
                    start = int(m.group(1) or 0)
                    end = int(m.group(2) or size - 1)
                    start = max(0, min(start, size - 1))
                    end = max(start, min(end, size - 1))
                    length = end - start + 1
                    self.send_response(206)
                    self.send_header("Content-Type", ctype)
                    self.send_header("Content-Length", str(length))
                    self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
                    self.send_header("Accept-Ranges", "bytes")
                    self.send_header("Cache-Control", "no-store")
                    self.end_headers()
                    with path.open("rb") as f:
                        f.seek(start)
                        self.wfile.write(f.read(length))
                    return
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(size))
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            with path.open("rb") as f:
                while True:
                    chunk = f.read(1024 * 512)
                    if not chunk:
                        break
                    self.wfile.write(chunk)

        def do_GET(self) -> None:
            path = urlparse(self.path).path
            if path in ["/", "/index.html"]:
                self.send_bytes(200, HTML.encode("utf-8"), "text/html; charset=utf-8")
            elif path == "/api/project":
                self.send_json(200, app.refresh())
            elif path.startswith("/media/"):
                name = path.rsplit("/", 1)[-1]
                self.send_file(app.asset(name), "font/ttf" if name == "font" else None)
            else:
                self.send_json(404, {"ok": False, "reason": "Not found"})

        def do_POST(self) -> None:
            if urlparse(self.path).path != "/api/save":
                self.send_json(404, {"ok": False, "reason": "Not found"})
                return
            try:
                payload = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0") or "0")).decode("utf-8"))
            except Exception as exc:
                self.send_json(400, {"ok": False, "reason": str(exc)})
                return
            self.send_json(200, app.save(payload))
    return Handler


def run_webeditor(project: str, host: str = "127.0.0.1", port: int = 8787, open_browser: bool = True) -> None:
    project_dir = Path(project)
    if not project_dir.is_absolute():
        project_dir = ROOT_DIR / project_dir
    if not project_dir.exists():
        raise FileNotFoundError(f"Project not found: {project_dir}")
    app = App(project_dir)
    server = ThreadingHTTPServer((host, port), handler_factory(app))
    url = f"http://{host}:{port}/"
    print(json.dumps({"ok": True, "mode": "webeditor_server_v2", "url": url, "project_dir": str(project_dir), "editor_project": str(project_dir / "editor" / "editor_project.json"), "clip_count": len(app.project.get("clips", [])), "note": "Range requests are enabled for audio seeking. Press Ctrl+C to stop."}, indent=2, ensure_ascii=False))
    if open_browser:
        threading.Timer(0.7, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nWebEditor stopped.")
    finally:
        server.server_close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Open EchoForge WebEditor v2.")
    parser.add_argument("--project", required=True)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    run_webeditor(args.project, args.host, args.port, not args.no_browser)


if __name__ == "__main__":
    main()
