from __future__ import annotations
import os

import json, math, os, subprocess, tempfile, time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple
from PIL import Image, ImageDraw, ImageFont, ImageFilter



# ef_background_layer_softness
# Browser preview and YouTube transcode can make hard-edged generated graphics look harsh.
# Keep final-video softness low, and soften the rendered background layer separately.
def _ef_env_float(name: str, default: float) -> float:
    try:
        return max(0.0, float(os.environ.get(name, str(default))))
    except Exception:
        return default


def render_softness_sigma() -> float:
    # Whole-frame softness. Keep this small because it also touches foreground lyrics.
    return _ef_env_float("ECHOFORGE_RENDER_SOFTNESS", 0.18)


def background_softness_sigma() -> float:
    # Background-only softness. This affects video_background.jpg/title/artist/background texture
    # before foreground lyrics are drawn, so generated background text is softened too.
    return _ef_env_float("ECHOFORGE_BACKGROUND_SOFTNESS", 0.55)


ProgressCallback = Callable[[Dict[str, Any]], None]

def emit(cb, **kw):
    if cb: cb(kw)

def read_json(p: Path, default=None):
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else default

def write_json(p: Path, data):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

def f(x, d=0.0):
    try: return float(x if x is not None else d)
    except Exception: return d

def i(x, d=0):
    try: return int(float(x if x is not None else d))
    except Exception: return d

def repo_root(project_dir: Path) -> Path:
    try: return project_dir.parents[1]
    except Exception: return Path.cwd()

def resolve_path(project_dir: Path, value: Any) -> Optional[Path]:
    if not value: return None
    raw = str(value).replace("\\", "/")
    if raw.startswith("/media/"): raw = raw[len("/media/"):]
    p = Path(raw)
    if p.is_absolute(): return p
    for c in (project_dir / raw, repo_root(project_dir) / raw, Path.cwd() / raw):
        if c.exists(): return c.resolve()
    return (project_dir / raw).resolve()

def clip_type(c):
    t = str(c.get("type") or c.get("kind") or c.get("clipType") or "").lower()
    tr = str(c.get("track") or c.get("trackId") or "").lower()
    cid = str(c.get("id") or "").lower()
    if t in ("lyric","lyrics","text") or "lyric" in tr or "lyric" in cid or c.get("text") is not None: return "lyric"
    if t in ("audio","sound") or "audio" in tr or "audio" in cid: return "audio"
    if t in ("background","image","bg","video_background") or "background" in tr or "bg" in cid: return "background"
    return t or "unknown"

def start(c): return f(c.get("start", c.get("startTime", c.get("from", 0))), 0)
def end(c):
    if c.get("end") is not None: return f(c.get("end"), 0)
    if c.get("endTime") is not None: return f(c.get("endTime"), 0)
    return start(c) + max(0, f(c.get("duration"), 0))
def dur(c): return max(0, end(c) - start(c))
def source_start(c): return f(c.get("sourceStart", c.get("source_start", c.get("trimStart", c.get("mediaStart",0)))), 0)

def clip_path(project_dir: Path, c):
    for k in ("path","src","source","file","asset","url"):
        if c.get(k): return resolve_path(project_dir, c.get(k))
    m = c.get("media")
    if isinstance(m, dict):
        for k in ("path","src","source","file","url"):
            if m.get(k): return resolve_path(project_dir, m.get(k))
    return None

def clips_from(project):
    if isinstance(project.get("clips"), list): return project["clips"]
    tl = project.get("timeline")
    if isinstance(tl, dict):
        if isinstance(tl.get("clips"), list): return tl["clips"]
        tracks = tl.get("tracks") or []
    else:
        tracks = project.get("tracks") or []
    out=[]
    for tr in tracks:
        if isinstance(tr, dict):
            for c in tr.get("clips", []):
                if isinstance(c, dict):
                    cc=dict(c); cc.setdefault("track", tr.get("id") or tr.get("name")); out.append(cc)
    return out

def canvas(project):
    c = project.get("canvas") if isinstance(project.get("canvas"), dict) else {}
    w,h = i(project.get("width", c.get("width")),1920), i(project.get("height", c.get("height")),1080)
    return (w,h) if w>=320 and h>=240 else (1920,1080)

def duration(project, clips):
    ends=[end(c) for c in clips if end(c)>0]
    return max(0.1, max(ends)) if ends else max(0.1, f(project.get("duration"), 0))

def color(v, default=(0,0,0)):
    if not isinstance(v, str): return default
    s=v.strip();
    if s.lower()=="black": return (0,0,0)
    if s.lower()=="white": return (255,255,255)
    if s.startswith("#"): s=s[1:]
    if len(s)==3: s="".join(ch*2 for ch in s)
    try: return (int(s[0:2],16), int(s[2:4],16), int(s[4:6],16))
    except Exception: return default

def font_path(root: Path, requested=None):
    if requested and Path(str(requested)).exists(): return Path(str(requested))
    for p in [root/"assets/fonts/Bernier/Bernier-Regular.ttf", root/"assets/fonts/Bernier/BERNIERRegular-Regular.ttf"]:
        if p.exists(): return p
    fd=root/"assets/fonts"
    if fd.exists():
        for p in list(fd.rglob("*.ttf"))+list(fd.rglob("*.otf")):
            if "bernier" in p.name.lower() or "bernier" in str(p.parent).lower(): return p
        for p in list(fd.rglob("*.ttf"))+list(fd.rglob("*.otf")): return p
    return None

def load_font(root: Path, size: int, requested=None):
    p=font_path(root, requested)
    if p:
        try: return ImageFont.truetype(str(p), size=max(8,size))
        except Exception: pass
    return ImageFont.load_default()

def cover(img: Image.Image, size):
    w,h=img.size; tw,th=size
    scale=max(tw/w, th/h); nw,nh=int(w*scale), int(h*scale)
    img=img.resize((nw,nh), Image.Resampling.LANCZOS)
    return img.crop(((nw-tw)//2,(nh-th)//2,(nw-tw)//2+tw,(nh-th)//2+th)).convert("RGB")

def background_at(project_dir, clips, t, size, cache):
    active=None
    for c in clips:
        if clip_type(c)=="background" and start(c)<=t<end(c): active=c; break
    if not active: return Image.new("RGB", size, (255,255,255))
    p=clip_path(project_dir, active)
    if not p or not p.exists():
        fb=project_dir/"images/video_background.jpg"; p=fb if fb.exists() else None
    if not p: return Image.new("RGB", size, (255,255,255))
    key=str(p)
    if key not in cache:
        try: img = cover(Image.open(p).convert("RGB"), size)
            sigma = background_softness_sigma()
            if sigma > 0:
                img = img.filter(ImageFilter.GaussianBlur(radius=sigma))
            cache[key] = img  # ef_background_layer_softened_cache
        except Exception: cache[key]=Image.new("RGB", size, (255,255,255))
    return cache[key].copy()

def pos(v, total, default):
    x=f(v, default)
    if 0<=x<=1: return int(x*total)
    if 1<x<=100: return int((x/100)*total)
    return int(x)

def style_dict(c):
    st = c.get("style") if isinstance(c, dict) else None
    return st if isinstance(st, dict) else {}

def get_style_value(c, keys, default=None, prefer_style=False):
    """Read values from both current WebEditor V3 style dict and older top-level fields."""
    st = style_dict(c)
    pools = (st, c) if prefer_style else (c, st)
    aliases = {
        "fontSize": ["fontSize", "font_size", "size"],
        "font_size": ["font_size", "fontSize", "size"],
        "fontFamily": ["fontFamily", "font_family", "family", "font"],
        "font_family": ["font_family", "fontFamily", "family", "font"],
        "fontPath": ["fontPath", "font_path"],
        "font_path": ["font_path", "fontPath"],
        "fontColor": ["fontColor", "color", "fill"],
        "color": ["color", "fontColor", "fill"],
        "fill": ["fill", "color", "fontColor"],
        "max_width": ["max_width", "maxWidth", "width"],
        "maxWidth": ["maxWidth", "max_width", "width"],
        "line_height": ["line_height", "lineHeight"],
        "lineHeight": ["lineHeight", "line_height"],
    }
    expanded = []
    for k in keys:
        expanded += aliases.get(k, [k])
    seen=set(); expanded=[k for k in expanded if not (k in seen or seen.add(k))]
    for pool in pools:
        for k in expanded:
            v = pool.get(k) if isinstance(pool, dict) else None
            if v is not None and v != "":
                return v
    return default

def wrap_text_to_width(text: str, font, max_width: int | None):
    if not max_width or max_width <= 20:
        return text
    lines=[]
    for raw in str(text).splitlines() or [str(text)]:
        words=raw.split()
        if not words:
            lines.append(""); continue
        cur=words[0]
        for word in words[1:]:
            trial=cur+" "+word
            try:
                b=font.getbbox(trial); w=b[2]-b[0]
            except Exception:
                w=len(trial)*10
            if w <= max_width:
                cur=trial
            else:
                lines.append(cur); cur=word
        lines.append(cur)
    return "\n".join(lines)

def draw_center(draw, xy, text, font, fill, max_width=None, spacing=8):
    text = wrap_text_to_width(text, font, max_width)
    try:
        b=draw.multiline_textbbox((0,0), text, font=font, spacing=spacing, align="center"); tw,th=b[2]-b[0], b[3]-b[1]
    except Exception: tw,th=draw.textlength(text,font=font),40
    x,y=xy; draw.multiline_text((int(x-tw/2), int(y-th/2)), text, font=font, fill=fill, spacing=spacing, align="center")

def build_audio(project_dir, clips, total, work, cb=None):
    ac=[c for c in clips if clip_type(c)=="audio" and dur(c)>0]
    fallback=project_dir/"audio/source_audio.m4a"
    if not ac: return fallback if fallback.exists() else None
    if len(ac)==1:
        c=ac[0]; p=clip_path(project_dir,c) or fallback
        if p and p.exists() and abs(start(c))<.03 and abs(source_start(c))<.03 and end(c)>=total-.05: return p
    inputs=[]; parts=[]; labels=[]
    for idx,c in enumerate(ac):
        p=clip_path(project_dir,c) or fallback
        if not p or not p.exists(): continue
        inputs.append(p); ss=max(0,source_start(c)); dd=max(.01,dur(c)); de=int(max(0,start(c))*1000); lab=f"a{idx}"; labels.append(lab)
        parts.append(f"[{idx}:a]atrim=start={ss:.3f}:end={ss+dd:.3f},asetpts=PTS-STARTPTS,adelay={de}|{de}[{lab}]")
    if not inputs: return None
    out=work/"audio_timeline.m4a"
    fc = parts[0]+f";[{labels[0]}]apad,atrim=0:{total:.3f}[aout]" if len(labels)==1 else ";".join(parts)+";"+"".join(f"[{x}]" for x in labels)+f"amix=inputs={len(labels)}:duration=longest,apad,atrim=0:{total:.3f}[aout]"
    cmd=["ffmpeg","-y"]
    for p in inputs: cmd += ["-i", str(p)]
    cmd += ["-filter_complex", fc, "-map", "[aout]", "-t", f"{total:.3f}", "-c:a", "aac", "-b:a", "192k", str(out)]
    emit(cb, stage="audio", message="Building edited audio timeline", progress=.03)
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    return out

def export_editor_project(project: str|Path, output: str|Path|None=None, fps:int=24, quality_crf:int=20, progress_callback:Optional[ProgressCallback]=None):
    project_dir=Path(project); project_dir=(Path.cwd()/project_dir if not project_dir.is_absolute() else project_dir).resolve()
    root=repo_root(project_dir); ep=project_dir/"editor/editor_project.json"
    if not ep.exists(): return {"ok":False,"stage":"render","reason":f"Missing editor project: {ep}"}
    data=read_json(ep,{}); clips=clips_from(data)
    if not clips: return {"ok":False,"stage":"render","reason":"No clips found in editor_project.json"}
    size=canvas(data); total=duration(data,clips); fps=max(1,int(fps)); frames=max(1,int(math.ceil(total*fps)))
    out=Path(output) if output else project_dir/"renders/final_video.mp4"
    if not out.is_absolute(): out=(project_dir/out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    emit(progress_callback, stage="render", message="Preparing render", progress=0, duration=total, frames=frames)
    with tempfile.TemporaryDirectory(prefix="ef_render_") as td:
        work=Path(td); audio=build_audio(project_dir,clips,total,work,progress_callback)
        cmd=["ffmpeg","-y","-f","rawvideo","-pix_fmt","rgb24","-s",f"{size[0]}x{size[1]}","-r",str(fps),"-i","-"]
        if audio and audio.exists(): cmd += ["-i", str(audio)]
        cmd += ["-t", f"{total:.3f}"]
        softness = render_softness_sigma()
        if softness > 0:
            cmd += ["-vf", f"gblur=sigma={softness:.3f}"]
        cmd += ["-c:v", "libx264", "-preset", "medium", "-crf", str(quality_crf), "-pix_fmt", "yuv420p"]
        cmd += (["-map","0:v:0","-map","1:a:0","-c:a","aac","-b:a","192k","-shortest"] if audio and audio.exists() else ["-map","0:v:0","-an"])
        cmd += [str(out)]
        proc=subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        cache={}; last=time.time()
        try:
            for n in range(frames):
                t=n/fps; frame=background_at(project_dir,clips,t,size,cache); d=ImageDraw.Draw(frame)
                for c in [x for x in clips if clip_type(x)=="lyric" and start(x)<=t<end(x)]:
                    text=str(c.get("text", ""));
                    if not text: continue
                    # WebEditor V3 stores edited style in clip.style; older generators used style.font_size/fill.
                    fs=i(get_style_value(c,["fontSize","font_size","size"],50,prefer_style=True),50)
                    font_req=get_style_value(c,["fontPath","font_path","fontFamily","font_family"],None,prefer_style=True)
                    font=load_font(root,fs,font_req)
                    x=pos(get_style_value(c,["x","left"],None,prefer_style=False), size[0], size[0]//2)
                    y=pos(get_style_value(c,["y","top"],None,prefer_style=False), size[1], size[1]//2)
                    max_w=i(get_style_value(c,["width","max_width","maxWidth"],0,prefer_style=False),0)
                    if max_w and 0 < max_w <= 1: max_w=int(max_w*size[0])
                    fill=color(get_style_value(c,["fontColor","color","fill"],"#000000",prefer_style=True))
                    line_h=f(get_style_value(c,["lineHeight","line_height"],1.05,prefer_style=True),1.05)
                    spacing=max(0,int(fs*(line_h-1.0)))
                    draw_center(d,(x,y),text,font,fill,max_width=max_w,spacing=spacing)
                proc.stdin.write(frame.tobytes())
                if time.time()-last>.5 or n==frames-1:
                    emit(progress_callback, stage="render", message=f"Rendering frame {n+1}/{frames}", progress=.05+.9*((n+1)/frames), frame=n+1, frames=frames); last=time.time()
            proc.stdin.close(); err=proc.stderr.read().decode("utf-8",errors="ignore") if proc.stderr else ""; code=proc.wait()
            if code!=0: return {"ok":False,"stage":"render","reason":"ffmpeg render failed","stderr":err[-4000:],"output":str(out)}
        finally:
            try:
                if proc.stdin and not proc.stdin.closed: proc.stdin.close()
            except Exception: pass
            if proc.poll() is None: proc.kill()
    report={"ok":True,"stage":"render","mode":"editor_project_export","project_dir":str(project_dir),"editor_project":str(ep),"output":str(out),"duration":total,"fps":fps,"frames":frames,"size":{"width":size[0],"height":size[1]},"clip_count":len(clips),"softness":{"final_video":render_softness_sigma(),"background_layer":background_softness_sigma()},"created_at":time.strftime("%Y-%m-%dT%H:%M:%S%z")}
    write_json(project_dir/"renders/render_report.json",report); emit(progress_callback,stage="render",message="Render complete",progress=.96,output=str(out)); return report

def main():
    import argparse
    p=argparse.ArgumentParser(); p.add_argument("--project",required=True); p.add_argument("--output"); p.add_argument("--fps",type=int,default=24); p.add_argument("--crf",type=int,default=20); a=p.parse_args()
    print(json.dumps(export_editor_project(a.project,a.output,a.fps,a.crf,lambda x: print(x.get("message",x),flush=True)),indent=2,ensure_ascii=False))
if __name__=="__main__": main()
