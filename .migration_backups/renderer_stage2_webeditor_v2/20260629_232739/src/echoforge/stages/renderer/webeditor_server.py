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
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def fnum(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def resolve_path(project_dir: Path, value: Any) -> Path | None:
    if not value:
        return None
    p = Path(str(value))
    candidates = [p] if p.is_absolute() else [project_dir / p, project_dir / "editor" / p, ROOT_DIR / p]
    for c in candidates:
        if c.exists():
            return c.resolve()
    return candidates[0].resolve() if candidates else None


def first_existing(paths: list[Path]) -> Path | None:
    for p in paths:
        if p.exists():
            return p.resolve()
    return None


def rel_to_project(project_dir: Path, path: Path | None) -> str:
    if not path:
        return ""
    try:
        return str(path.resolve().relative_to(project_dir.resolve())).replace("\\", "/")
    except Exception:
        try:
            return str(path.resolve().relative_to(ROOT_DIR.resolve())).replace("\\", "/")
        except Exception:
            return str(path)


def title_artist(project_dir: Path) -> dict[str, str]:
    state = read_json(project_dir / "project_state.json", {}) or {}
    review = read_json(project_dir / "metadata_review.json", {}) or {}
    song = state.get("song") if isinstance(state.get("song"), dict) else {}
    return {
        "title": str(review.get("display_title") or review.get("title") or song.get("title") or state.get("title") or project_dir.name),
        "artist": str(review.get("display_artist") or review.get("artist") or review.get("artist_text") or song.get("artist") or song.get("artists") or state.get("artist") or ""),
    }


def parse_lrc(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    pat = re.compile(r"\[(\d+):(\d+(?:\.\d+)?)\]\s*(.*)")
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        m = pat.match(line.strip())
        if not m:
            continue
        text = m.group(3).strip()
        if not text:
            continue
        rows.append({"start": int(m.group(1)) * 60 + float(m.group(2)), "text": text})
    for i, row in enumerate(rows):
        row["end"] = (rows[i + 1]["start"] - 0.05) if i + 1 < len(rows) else row["start"] + 3.0
        if row["end"] <= row["start"]:
            row["end"] = row["start"] + 1.0
    return rows


def sync_lines(project_dir: Path) -> list[dict[str, Any]]:
    data = read_json(project_dir / "sync" / "final_synced_lyrics.json", None)
    candidates = None
    if isinstance(data, list):
        candidates = data
    elif isinstance(data, dict):
        for key in ["lines", "lyrics", "items", "clips", "segments"]:
            if isinstance(data.get(key), list):
                candidates = data[key]
                break
    rows: list[dict[str, Any]] = []
    if isinstance(candidates, list):
        for item in candidates:
            if not isinstance(item, dict):
                continue
            text = str(item.get("text") or item.get("line") or item.get("lyric") or item.get("content") or "").strip()
            if not text:
                continue
            start = fnum(item.get("start") or item.get("start_time") or item.get("time") or item.get("timestamp"), 0.0)
            end = fnum(item.get("end") or item.get("end_time"), start + 2.5)
            rows.append({"start": start, "end": max(end, start + 0.35), "text": text})
    if not rows:
        rows = parse_lrc(project_dir / "sync" / "final_synced_lyrics.lrc")
    rows.sort(key=lambda r: fnum(r.get("start"), 0.0))
    return rows


def normalize_clip(item: dict[str, Any], idx: int, style: dict[str, Any]) -> dict[str, Any]:
    text = str(item.get("text") or item.get("line") or item.get("lyric") or "").strip()
    start = fnum(item.get("start") or item.get("start_time") or item.get("time"), 0.0)
    end = max(fnum(item.get("end") or item.get("end_time"), start + 2.5), start + 0.35)
    item_style = item.get("style") if isinstance(item.get("style"), dict) else {}
    return {
        "id": str(item.get("id") or f"clip_{idx:04d}"),
        "type": "lyric",
        "text": text,
        "start": round(start, 3),
        "end": round(end, 3),
        "x": int(fnum(item.get("x") if item.get("x") is not None else item_style.get("x"), style["x"])),
        "y": int(fnum(item.get("y") if item.get("y") is not None else item_style.get("y"), style["y"])),
        "font_family": str(item.get("font_family") or item_style.get("font_family") or style["font_family"]),
        "font_size": int(fnum(item.get("font_size") if item.get("font_size") is not None else item_style.get("font_size"), style["font_size"])),
        "color": str(item.get("color") or item_style.get("color") or style["color"]),
        "align": str(item.get("align") or item_style.get("align") or style["align"]),
        "visible": bool(item.get("visible", True)),
    }


def load_project(project_dir: Path) -> dict[str, Any]:
    project_dir = project_dir.resolve()
    editor_dir = project_dir / "editor"
    editor_path = editor_dir / "editor_project.json"
    raw = read_json(editor_path, {}) or {}
    canvas = raw.get("canvas") if isinstance(raw.get("canvas"), dict) else {}
    width, height = int(fnum(canvas.get("width"), 1920)), int(fnum(canvas.get("height"), 1080))
    style = {"font_family": "Bernier", "font_size": 50, "color": "#000000", "x": width // 2, "y": height // 2, "align": "center"}
    if isinstance(raw.get("style"), dict):
        style.update({k: v for k, v in raw["style"].items() if v is not None})

    assets = raw.get("assets") if isinstance(raw.get("assets"), dict) else {}
    background = resolve_path(project_dir, assets.get("background") or assets.get("background_path"))
    audio = resolve_path(project_dir, assets.get("audio") or assets.get("audio_path"))
    font = resolve_path(project_dir, assets.get("font") or assets.get("font_path"))

    background = background if background and background.exists() else first_existing([
        project_dir / "images" / "video_background.jpg",
        project_dir / "images" / "background_source.jpg",
    ])
    audio = audio if audio and audio.exists() else first_existing([
        project_dir / "audio" / "source_audio.m4a",
        project_dir / "audio" / "source_audio.mp3",
        project_dir / "audio" / "source_audio.wav",
        project_dir / "audio" / "source_audio.webm",
        project_dir / "audio" / "source_audio.mp4",
    ])
    font = font if font and font.exists() else first_existing([
        ROOT_DIR / "assets" / "fonts" / "Bernier" / "Bernier-Regular.ttf",
        ROOT_DIR / "assets" / "fonts" / "Bernier-Regular.ttf",
    ])

    raw_clips = raw.get("clips") if isinstance(raw.get("clips"), list) else None
    if raw_clips is None and isinstance(raw.get("timeline"), dict) and isinstance(raw["timeline"].get("clips"), list):
        raw_clips = raw["timeline"]["clips"]
    if raw_clips is None:
        raw_clips = sync_lines(project_dir)

    clips = [normalize_clip(c, i + 1, style) for i, c in enumerate(raw_clips) if isinstance(c, dict)]
    clips = [c for c in clips if c["text"]]
    clips.sort(key=lambda c: c["start"])
    meta = title_artist(project_dir)
    project = {
        "schema_version": "echoforge.webeditor.v2",
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "project": {"project_dir": str(project_dir), "title": meta["title"], "artist": meta["artist"]},
        "canvas": {"width": width, "height": height, "fps": 30},
        "assets": {"background": rel_to_project(project_dir, background), "audio": rel_to_project(project_dir, audio), "font": rel_to_project(project_dir, font)},
        "style": style,
        "clips": clips,
    }
    editor_dir.mkdir(parents=True, exist_ok=True)
    write_json(editor_path, project)
    write_json(editor_dir / "timeline.json", {"clips": clips, "updated_at": project["updated_at"]})
    return project


HTML = r"""<!doctype html>
<html><head><meta charset="utf-8"><title>EchoForge WebEditor</title>
<style>
:root{--panel:rgba(17,17,20,.88);--text:#f4f4f4;--muted:#a7a7a7}
*{box-sizing:border-box}body{margin:0;height:100vh;background:#0e0e10;color:var(--text);font-family:system-ui,-apple-system,Segoe UI,sans-serif;overflow:hidden}
@font-face{font-family:'Bernier';src:url('/media/font') format('truetype');font-display:swap}
.app{display:grid;grid-template-columns:1fr 390px;height:100vh}.left{display:grid;grid-template-rows:1fr auto;gap:12px;padding:18px;min-width:0}
.stageWrap{display:grid;place-items:center;background:radial-gradient(circle,#24242a,#111);border:1px solid #333;border-radius:18px;overflow:hidden;min-height:0}
.stage{position:relative;width:min(100%,calc((100vh - 150px)*16/9));aspect-ratio:16/9;background:#111;overflow:hidden;user-select:none}
.bg{position:absolute;inset:0;width:100%;height:100%;object-fit:cover}.lyric{position:absolute;transform:translate(-50%,-50%);max-width:86%;padding:10px 18px;border:1px dashed transparent;text-align:center;white-space:pre-wrap;line-height:1.1;cursor:move;font-family:'Bernier',Impact,sans-serif}
.lyric.selected{border-color:rgba(255,255,255,.6);background:rgba(255,255,255,.08);border-radius:8px}
.controls,.side,.status{background:var(--panel);border:1px solid #303038;border-radius:16px;box-shadow:0 18px 40px rgba(0,0,0,.28)}
.controls{padding:12px;display:grid;gap:10px}.row{display:flex;gap:8px;align-items:center;flex-wrap:wrap}
button,input,textarea{background:#181820;color:var(--text);border:1px solid #3a3a44;border-radius:10px;padding:9px 11px;font:inherit}button{cursor:pointer}button:hover{background:#242432}
input[type=range]{flex:1;min-width:180px}audio{width:100%;height:34px}.side{height:100vh;padding:14px;display:grid;grid-template-rows:auto auto 1fr auto;gap:12px;overflow:hidden}
.title{font-size:18px;font-weight:800}.muted{color:var(--muted);font-size:12px}.editorBox{display:grid;gap:8px;padding:12px;border:1px solid #303038;border-radius:14px;background:rgba(0,0,0,.18)}
textarea{width:100%;min-height:86px;resize:vertical}label{color:var(--muted);font-size:12px;display:grid;gap:4px}.grid2{display:grid;grid-template-columns:1fr 1fr;gap:8px}
.timeline{overflow:auto;border:1px solid #303038;border-radius:14px;background:rgba(0,0,0,.18)}.clip{display:grid;grid-template-columns:74px 1fr;gap:8px;padding:9px 10px;border-bottom:1px solid #2b2b32;cursor:pointer}.clip:hover{background:rgba(255,255,255,.05)}.clip.active{background:rgba(255,255,255,.12)}
.clipTime{color:#b8b8c5;font-variant-numeric:tabular-nums;font-size:12px}.clipText{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.status{padding:10px;color:var(--muted);font-size:12px;white-space:pre-wrap}.ok{color:#75e087}.bad{color:#ff8585}
</style></head>
<body><div class="app"><div class="left"><div class="stageWrap"><div id="stage" class="stage"><img id="bg" class="bg"><div id="lyric" class="lyric"></div></div></div>
<div class="controls"><div class="row"><button id="playBtn">Play</button><button id="backBtn">−5s</button><button id="fwdBtn">+5s</button><span id="clock" class="muted">00:00 / 00:00</span></div><div class="row"><input id="seek" type="range" min="0" max="1000" value="0"></div><audio id="audio" controls preload="metadata"></audio></div></div>
<aside class="side"><div><div class="title">EchoForge WebEditor</div><div id="song" class="muted"></div><div id="fontStatus" class="muted">Font: checking...</div></div>
<div class="editorBox"><div class="muted">Selected clip</div><textarea id="clipText"></textarea><div class="grid2"><label>Start <input id="startInput" type="number" step="0.01"></label><label>End <input id="endInput" type="number" step="0.01"></label><label>X <input id="xInput" type="number"></label><label>Y <input id="yInput" type="number"></label><label>Font size <input id="fontSizeInput" type="number"></label><label>Color <input id="colorInput" type="color"></label></div><div class="row"><button id="applyBtn">Apply selected</button><button id="applyAllBtn">Apply style to all</button></div><div class="row"><button id="saveBtn">Save editor_project.json</button></div></div>
<div id="timeline" class="timeline"></div><div id="status" class="status">Loading...</div></aside></div>
<script>
let state=null,selectedIndex=0,dragging=false;const el=id=>document.getElementById(id),audio=el('audio'),stage=el('stage'),lyric=el('lyric'),seek=el('seek');
function fmt(t){if(!isFinite(t))return'00:00';let m=Math.floor(t/60),s=Math.floor(t%60);return`${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')}`}function log(m,g=true){el('status').innerHTML=`<span class="${g?'ok':'bad'}">${m}</span>`}function esc(s){return String(s).replace(/[&<>"']/g,ch=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]))}
function currentIndex(){let t=audio.currentTime||0,cs=state.clips||[],i=cs.findIndex(c=>t>=+c.start&&t<+c.end);if(i<0){for(let j=0;j<cs.length;j++)if(+cs[j].start>t)return Math.max(0,j-1);i=Math.max(0,cs.length-1)}return i}
function fill(c){el('clipText').value=c.text||'';el('startInput').value=(+c.start).toFixed(2);el('endInput').value=(+c.end).toFixed(2);el('xInput').value=Math.round(+(c.x||state.style.x||960));el('yInput').value=Math.round(+(c.y||state.style.y||540));el('fontSizeInput').value=Math.round(+(c.font_size||state.style.font_size||50));el('colorInput').value=c.color||state.style.color||'#000000'}
function setSel(i,seekIt=false){if(!state||!state.clips.length)return;selectedIndex=Math.max(0,Math.min(i,state.clips.length-1));let c=state.clips[selectedIndex];fill(c);if(seekIt)audio.currentTime=+c.start||0;drawTimeline();drawLyric()}
function drawLyric(){if(!state||!state.clips.length)return;let i=dragging?selectedIndex:currentIndex(),c=state.clips[i]||state.clips[selectedIndex];selectedIndex=i;lyric.textContent=c.text||'';lyric.style.left=`${(+(c.x||960)/state.canvas.width)*100}%`;lyric.style.top=`${(+(c.y||540)/state.canvas.height)*100}%`;lyric.style.fontSize=`${+(c.font_size||state.style.font_size||50)*(stage.clientWidth/state.canvas.width)}px`;lyric.style.color=c.color||state.style.color||'#000000';lyric.style.textAlign=c.align||'center';lyric.classList.add('selected');fill(c);document.querySelectorAll('.clip').forEach((n,k)=>n.classList.toggle('active',k===i))}
function drawTimeline(){let box=el('timeline');box.innerHTML='';state.clips.forEach((c,i)=>{let r=document.createElement('div');r.className='clip'+(i===selectedIndex?' active':'');r.innerHTML=`<div class="clipTime">${fmt(c.start)}<br>${fmt(c.end)}</div><div class="clipText">${esc(c.text||'')}</div>`;r.onclick=()=>setSel(i,true);box.appendChild(r)})}
function applySelected(){let c=state.clips[selectedIndex];c.text=el('clipText').value;c.start=+el('startInput').value;c.end=Math.max(+el('endInput').value,c.start+.1);c.x=+el('xInput').value;c.y=+el('yInput').value;c.font_size=+el('fontSizeInput').value;c.color=el('colorInput').value;drawTimeline();drawLyric();log('Applied selected clip. Click Save.')}
function applyAll(){let c=state.clips[selectedIndex];for(let it of state.clips){it.x=+c.x;it.y=+c.y;it.font_size=+c.font_size;it.color=c.color;it.align=c.align||'center'}Object.assign(state.style,{x:+c.x,y:+c.y,font_size:+c.font_size,color:c.color});drawTimeline();drawLyric();log('Applied style to all clips. Click Save.')}
async function save(){applySelected();let r=await fetch('/api/save',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(state)}),d=await r.json();log(d.ok?'Saved editor_project.json and timeline.json':(d.reason||'Save failed'),!!d.ok)}
function seekBy(d){audio.currentTime=Math.max(0,Math.min(audio.duration||0,(audio.currentTime||0)+d));drawLyric()}function toggle(){audio.paused?audio.play():audio.pause()}function clock(){el('clock').textContent=`${fmt(audio.currentTime||0)} / ${fmt(audio.duration||0)}`;if(audio.duration)seek.value=Math.round(((audio.currentTime||0)/audio.duration)*1000)}
function point(e){let r=stage.getBoundingClientRect();return{x:((e.clientX-r.left)/r.width)*state.canvas.width,y:((e.clientY-r.top)/r.height)*state.canvas.height}}
lyric.onmousedown=e=>{dragging=true;e.preventDefault()};window.onmousemove=e=>{if(!dragging||!state)return;let p=point(e),c=state.clips[selectedIndex];c.x=Math.round(p.x);c.y=Math.round(p.y);el('xInput').value=c.x;el('yInput').value=c.y;drawLyric()};window.onmouseup=()=>{if(dragging)log('Position changed. Click Save.');dragging=false}
el('playBtn').onclick=toggle;el('backBtn').onclick=()=>seekBy(-5);el('fwdBtn').onclick=()=>seekBy(5);el('applyBtn').onclick=applySelected;el('applyAllBtn').onclick=applyAll;el('saveBtn').onclick=save;seek.oninput=()=>{if(audio.duration)audio.currentTime=(+seek.value/1000)*audio.duration}
audio.ontimeupdate=()=>{clock();let i=currentIndex();if(i!==selectedIndex)selectedIndex=i;drawLyric()};audio.onloadedmetadata=clock;audio.onplay=()=>el('playBtn').textContent='Pause';audio.onpause=()=>el('playBtn').textContent='Play';
document.addEventListener('keydown',e=>{let tag=document.activeElement?.tagName?.toLowerCase();if(tag==='input'||tag==='textarea')return;if(e.code==='Space'){e.preventDefault();toggle()}if(e.code==='ArrowLeft'){e.preventDefault();seekBy(-5)}if(e.code==='ArrowRight'){e.preventDefault();seekBy(5)}},true);
(async()=>{let r=await fetch('/api/project');state=await r.json();el('song').textContent=`${state.project.title||''} — ${state.project.artist||''}`;el('bg').src='/media/background';audio.src='/media/audio';try{await document.fonts.load('50px Bernier');let ok=[...document.fonts].some(f=>f.family==='Bernier'&&f.status==='loaded');el('fontStatus').innerHTML=ok?'<span class="ok">Font: Bernier loaded</span>':'<span class="bad">Font: Bernier not loaded</span>'}catch(e){el('fontStatus').innerHTML='<span class="bad">Font: Bernier failed</span>'}drawTimeline();setSel(0,false);log(`Loaded ${state.clips.length} lyric clips. Drag lyrics to reposition. Space = play/pause.`)})().catch(e=>log(String(e),false))
</script></body></html>"""


class App:
    def __init__(self, project_dir: Path):
        self.project_dir = project_dir.resolve()
        self.project = load_project(self.project_dir)

    def refresh(self) -> dict[str, Any]:
        self.project = load_project(self.project_dir)
        return self.project

    def asset(self, name: str) -> Path | None:
        key = {"background": "background", "audio": "audio", "font": "font"}.get(name)
        return resolve_path(self.project_dir, self.project.get("assets", {}).get(key)) if key else None

    def save(self, data: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(data, dict) or not isinstance(data.get("clips"), list):
            return {"ok": False, "reason": "Invalid editor project payload."}
        data["updated_at"] = datetime.now(timezone.utc).isoformat()
        data.setdefault("schema_version", "echoforge.webeditor.v2")
        editor_dir = self.project_dir / "editor"
        write_json(editor_dir / "editor_project.json", data)
        write_json(editor_dir / "timeline.json", {"clips": data["clips"], "updated_at": data["updated_at"]})
        self.project = data
        return {"ok": True, "clip_count": len(data["clips"]), "editor_project": str(editor_dir / "editor_project.json")}


def handler_factory(app: App):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *args: Any) -> None:
            sys.stderr.write("[WebEditor] " + fmt % args + "\n")

        def send_body(self, status: int, body: bytes, ctype: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(body)

        def send_json(self, status: int, data: Any) -> None:
            self.send_body(status, json.dumps(data, indent=2, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

        def do_GET(self) -> None:
            path = urlparse(self.path).path
            if path in ["/", "/index.html"]:
                self.send_body(200, HTML.encode("utf-8"), "text/html; charset=utf-8")
            elif path == "/api/project":
                self.send_json(200, app.refresh())
            elif path.startswith("/media/"):
                name = path.rsplit("/", 1)[-1]
                p = app.asset(name)
                if not p or not p.exists():
                    self.send_json(404, {"ok": False, "reason": f"Missing media: {name}", "path": str(p) if p else None})
                    return
                self.send_body(200, p.read_bytes(), mimetypes.guess_type(str(p))[0] or "application/octet-stream")
            else:
                self.send_json(404, {"ok": False, "reason": "Not found"})

        def do_POST(self) -> None:
            if urlparse(self.path).path != "/api/save":
                self.send_json(404, {"ok": False, "reason": "Not found"})
                return
            body = self.rfile.read(int(self.headers.get("Content-Length", "0") or "0"))
            try:
                payload = json.loads(body.decode("utf-8"))
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
    httpd = ThreadingHTTPServer((host, port), handler_factory(app))
    url = f"http://{host}:{port}/"
    if open_browser:
        threading.Timer(0.7, lambda: webbrowser.open(url)).start()
    print(json.dumps({
        "ok": True,
        "mode": "webeditor_server",
        "url": url,
        "project_dir": str(project_dir),
        "editor_project": str(project_dir / "editor" / "editor_project.json"),
        "clip_count": len(app.project.get("clips", [])),
        "note": "Press Ctrl+C to stop the WebEditor server."
    }, indent=2, ensure_ascii=False))
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nWebEditor stopped.")
    finally:
        httpd.server_close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Open EchoForge WebEditor.")
    parser.add_argument("--project", required=True)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    run_webeditor(args.project, args.host, args.port, not args.no_browser)


if __name__ == "__main__":
    main()
