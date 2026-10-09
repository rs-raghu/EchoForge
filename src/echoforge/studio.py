"""Web Studio API backed by the canonical project folders and pipeline services."""
from __future__ import annotations

import copy
import re
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from echoforge.core.paths import ROOT_DIR, PROJECTS_DIR, APP_STATE_DIR
from echoforge.core.storage import atomic_json, read_json, file_lock
from echoforge.core.media import audio_duration, fingerprint
from echoforge.core.security import asset_path, number
from echoforge.core import project_builder
from echoforge.stages.renderer import render_jobs
from echoforge.stages.renderer.editor_project_v2 import load_final_lines, make_v2_project
from echoforge.stages.songscout.cleaner import unique_song_id
from echoforge.stages.songscout.database import upsert_songs
from echoforge.stages.tubeharbor.youtube_uploader import privacy

app = FastAPI(title="EchoForge Studio", version="1.0.0")
DEFAULT_DESIGN = {"template":"Classic", "aspectRatio":"16:9", "resolution":"1080p", "fps":24,
                  "backgroundType":"solid", "backgroundColor":"#ffffff", "fontFamily":"Bernier", "fontSize":50,
                  "textColor":"#000000", "highlightColor":"#000000", "animation":"none", "textPosition":"center", "watermark":False}
DEFAULT_SETTINGS = {"theme":"dark", "defaultCountry":"GLOBAL", "defaultPrivacy":"private", "autosaveSeconds":2,
                    "renderQuality":"standard", "previewResolution":"720p", "workspaceRoot":str(PROJECTS_DIR),
                    "databasePath":str(ROOT_DIR / "data/songscout/songscout.sqlite3"), "remotionPath":""}


def now():
    return datetime.now(timezone.utc).isoformat()


@app.middleware("http")
async def local_boundary(request: Request, call_next):
    if request.url.hostname not in {"127.0.0.1", "localhost", "::1", "testserver"}:
        return JSONResponse({"error":"Local host required"}, status_code=403)
    origin = request.headers.get("origin")
    if origin and origin != str(request.base_url).rstrip("/"):
        return JSONResponse({"error":"Same-origin request required"}, status_code=403)
    if request.headers.get("sec-fetch-site") == "cross-site":
        return JSONResponse({"error":"Cross-site request denied"}, status_code=403)
    if request.method in {"POST", "PUT"}:
        if request.headers.get("content-type", "").split(";")[0] != "application/json":
            return JSONResponse({"error":"JSON required"}, status_code=415)
        length = request.headers.get("content-length")
        if not length or not length.isdigit() or int(length) > 8 * 1024 * 1024:
            return JSONResponse({"error":"Invalid request size"}, status_code=413)
    try:
        return await call_next(request)
    except (ValueError, TypeError) as exc:
        return JSONResponse({"error":str(exc)}, status_code=422)


def project_path(project_id: str):
    if not re.fullmatch(r"[A-Za-z0-9_-]+", project_id):
        raise HTTPException(400, "Invalid project ID")
    path = (PROJECTS_DIR / project_id).resolve()
    if not path.is_relative_to(PROJECTS_DIR.resolve()) or not (path / "project_state.json").is_file():
        raise HTTPException(404, "Project not found")
    return path


def nonempty(path):
    return path.is_file() and path.stat().st_size > 0


def job_item(job):
    return {"id":int(job["job_id"], 16), "projectId":Path(job["project_dir"]).name,
            "jobType":job.get("options", {}).get("jobType", "render_final"), "status":job["status"],
            "progress":round(float(job.get("progress", 0))*100), "message":job.get("reason") or (job.get("logs") or [{}])[-1].get("message"),
            "errorMessage":job.get("reason"), "createdAt":job.get("created_at"), "startedAt":job.get("created_at"),
            "finishedAt":job.get("updated_at") if job["status"] not in render_jobs._ACTIVE_STATUSES else None,
            "cancelRequested":job.get("cancel_requested", False), "logPath":None}


def detail(path: Path):
    state = read_json(path / "project_state.json")
    report = read_json(path / "upload/youtube_upload_report.json", {})
    lyrics = path / "lyrics/lyrics.txt"
    timings = path / "sync/final_synced_lyrics.json"
    ready = {"audio":nonempty(path / "audio/source_audio.m4a"), "lyrics":nonempty(lyrics),
             "timestamps":nonempty(timings) or nonempty(path / "sync/final_synced_lyrics.lrc"),
             "draftTimestamps":nonempty(path / "studio/timestamps_draft.json") or nonempty(path / "sync/candidates/timestamp_transfer_candidate.json"),
             "preview":nonempty(path / "renders/preview_video.mp4"), "final":nonempty(path / "renders/final_video.mp4"),
             "published":bool(report.get("ok") and report.get("video_id")), "design":nonempty(path / "studio/design.json")}
    if ready["published"]: status, action = "uploaded", None
    elif ready["final"]: status, action = "rendered", "upload_youtube"
    elif ready["timestamps"]: status, action = "synced", "render_final"
    elif ready["lyrics"]: status, action = "lyrics_ready", "continue_video"
    else: status, action = "selected", "assets_only"
    tasks = [j for j in render_jobs.list_jobs() if j.get("project_dir") == str(path)]
    active = next((j for j in tasks if j["status"] in render_jobs._ACTIVE_STATUSES), None)
    if active: status, action = "processing", None
    files=[]
    for file in sorted(path.rglob("*")):
        if file.is_file() and not any(p.startswith(".") for p in file.relative_to(path).parts):
            stat=file.stat()
            files.append({"name":file.name, "relativePath":file.relative_to(path).as_posix(), "size":stat.st_size,
                          "updatedAt":datetime.fromtimestamp(stat.st_mtime,timezone.utc).isoformat(), "kind":file.suffix.lstrip(".")})
    checklist=[{"key":key, "label":key.title(), "done":ready[key]} for key in ["audio","lyrics","timestamps","design","final","published"]]
    return {"id":path.name, "videoId":report.get("video_id", ""), "title":state.get("title",path.name), "artist":state.get("artist", ""),
            "sourceUrl":state.get("source_youtube_url") or state.get("youtube_url", ""), "rawState":state.get("current_stage", "selected"),
            "studioState":status, "statusLabel":status.replace("_", " ").title(), "statusTone":"processing" if active else "success" if ready["published"] else "neutral",
            "microState":status, "targetState":"review", "workspacePath":str(path), "updatedAt":state.get("updated_at",now()),
            "progress":round(float(active.get("progress",0))*100) if active else round(sum(c["done"] for c in checklist)/len(checklist)*100),
            "nextAction":action or "Complete", "primaryAction":action, "checklist":checklist, "filesReady":ready, "files":files,
            "logs":[{"time":entry["time"], "level":"info", "projectId":path.name, "message":entry["message"]} for j in tasks for entry in j.get("logs",[])]}


@app.get("/api/projects")
def projects(limit: int = 200):
    return [detail(p.parent) for p in sorted(PROJECTS_DIR.glob("*/project_state.json"), reverse=True)[:max(1,min(limit,500))]]


@app.get("/api/projects/{project_id}")
def project(project_id: str):
    return detail(project_path(project_id))


@app.post("/api/projects")
def create_project(payload: dict):
    title, artist = str(payload.get("title", "")).strip(), str(payload.get("artist", "")).strip()
    if not title or not artist or max(len(title),len(artist)) > 300:
        raise ValueError("Title and artist are required (maximum 300 characters)")
    source = str(payload.get("sourceUrl", "")).strip()
    if source and not re.match(r"https://(?:www\.)?(?:youtube\.com|youtu\.be)/", source):
        raise ValueError("Source URL must be a YouTube HTTPS URL")
    song={"id":unique_song_id(title,artist), "title":title, "artist":artist, "youtube_url":source}
    upsert_songs([song])
    return detail(Path(project_builder.init_project_for_song(song)["project_dir"]))


@app.get("/api/dashboard")
def dashboard():
    items=projects(); counts={}
    for item in items: counts[item["studioState"]]=counts.get(item["studioState"],0)+1
    return {"summary":[{"key":key,"label":key.title(),"value":value,"tone":"neutral"} for key,value in counts.items()],
            "activeProjects":[p for p in items if p["studioState"] == "processing"], "queue":[p for p in items if not p["filesReady"]["published"]],
            "recentProjects":items[:12], "stateCounts":counts, "logs":logs()}


@app.get("/api/logs")
def logs(limit: int = 120):
    return sorted([entry for p in projects() for entry in p["logs"]],key=lambda x:x["time"], reverse=True)[:max(1,min(limit,500))]


@app.post("/api/queue/stage-next")
def stage_next():
    result=project_builder.init_next_project()
    if not result.get("ok"): raise HTTPException(409,result["reason"])
    return detail(Path(result["project_dir"]))


@app.post("/api/discovery/youtube-charts")
def discovery(payload: dict):
    from echoforge.stages.songscout.refresh import refresh_chart
    country=str(payload.get("country","GLOBAL")).upper()
    urls={"GLOBAL":"global", "IN":"in", "US":"us", "GB":"gb"}
    if country not in urls: raise ValueError("Unsupported chart country")
    # A per-country chart is passed explicitly; never mutate shared environment settings.
    result=refresh_chart(force=bool(payload.get("force",False)), max_songs=int(payload.get("limit",100)), country=urls[country])
    return {"added":result.get("inserted",0), "count":result.get("clean_songs",0), "skipped":not result["scraped"], "message":result.get("reason", "Chart refreshed")}


def versions(path, kind):
    return read_json(path / f"studio/{kind}_versions.json", [])


def save_version(path, kind, payload, approved):
    entries=versions(path,kind)
    target=path / f"studio/versions/{kind}_{uuid.uuid4().hex}.json"
    atomic_json(target,payload)
    entries.append({"id":len(entries)+1, "filePath":str(target), "versionLabel":f"Version {len(entries)+1}", "createdAt":now(),
                    "createdBy":"local", "isApproved":approved, "notes":None})
    atomic_json(path / f"studio/{kind}_versions.json", entries)


def lyric_rows(path):
    active=path / "studio/lyrics_current.json"; draft=path / "studio/lyrics_draft.json"
    if draft.exists(): return read_json(draft), "draft"
    if active.exists(): return read_json(active), "current"
    text=(path / "lyrics/lyrics.txt").read_text(encoding="utf-8") if (path / "lyrics/lyrics.txt").exists() else ""
    return [{"id":f"line_{i}","index":i,"type":"section_label" if re.fullmatch(r"\[.*\]",text) else "lyric","text":text,"timestamp":None} for i,text in enumerate(text.splitlines(),1)], "current"


def check_lyrics(lines):
    if not isinstance(lines,list) or len(lines)>20000: raise ValueError("Invalid lyric lines")
    ids=set()
    for line in lines:
        if not isinstance(line,dict) or not isinstance(line.get("text"),str) or len(line["text"])>10000:
            raise ValueError("Invalid lyric text")
        if not line.get("id") or line["id"] in ids or line.get("type") not in {"lyric","section_label","instrumental","note"}:
            raise ValueError("Invalid lyric ID or type")
        ids.add(line["id"])
    return lines


@app.get("/api/projects/{project_id}/lyrics")
def lyrics(project_id: str):
    path=project_path(project_id); lines,source=lyric_rows(path)
    return {"projectId":project_id,"source":source,"sourcePath":str(path/f"studio/lyrics_{source}.json"),"activePath":str(path/"lyrics/lyrics.txt"),
            "draftPath":str(path/"studio/lyrics_draft.json"),"format":"text","hasDraft":source=="draft","rawText":"\n".join(x["text"] for x in lines),
            "lines":lines,"warnings":[],"versions":versions(path,"lyrics")}


@app.put("/api/projects/{project_id}/lyrics")
def save_lyrics(project_id: str, payload: dict, draft: bool = True):
    path=project_path(project_id); lines=check_lyrics(payload.get("lines"))
    with file_lock(path/"studio/edit.lock"):
        atomic_json(path/f"studio/lyrics_{'draft' if draft else 'current'}.json",lines)
        if not draft:
            save_version(path,"lyrics",lines,False)
            (path/"studio/lyrics_draft.json").unlink(missing_ok=True)
    return lyrics(project_id)


@app.post("/api/projects/{project_id}/lyrics/approve")
def approve_lyrics(project_id: str, payload: dict):
    path=project_path(project_id); lines=check_lyrics(payload.get("lines"))
    text="\n".join(x["text"] for x in lines if x["type"] in {"lyric","section_label"})+"\n"
    if not any(x["text"].strip() for x in lines if x["type"]=="lyric"): raise ValueError("No lyric text to approve")
    from echoforge.core.storage import atomic_text, update_json
    with file_lock(path/"studio/edit.lock"):
        atomic_json(path/"studio/lyrics_current.json",lines)
        atomic_text(path/"lyrics/lyrics.txt",text)
        save_version(path,"lyrics",lines,True)
        (path/"studio/lyrics_draft.json").unlink(missing_ok=True)
        def invalidate(state):
            state.setdefault('stages',{}).update(verselock='needs_review',renderer='pending')
            state['lyrics_approved_sha256']=fingerprint(path/'lyrics/lyrics.txt')
        update_json(path/'project_state.json',invalidate)
    return lyrics(project_id)


def timestamp_rows(path):
    draft=path/"studio/timestamps_draft.json"
    if draft.exists(): return read_json(draft),"draft"
    lines=load_final_lines(path)
    if not lines:
        lines=read_json(path/"sync/candidates/timestamp_transfer_candidate.json",{}).get("lines",[])
    return [{"id":str(x.get("id") or f"segment_{i}"),"index":i,"start":x.get("start",x.get("start_seconds",0)),
             "end":x.get("end",x.get("end_seconds")) or x.get("start",x.get("start_seconds",0))+3,"text":x.get("text",""),"words":x.get("words",[])} for i,x in enumerate(lines,1)],"current"


def timing_check(path, segments):
    if not isinstance(segments,list) or len(segments)>20000: raise ValueError("Invalid timing segments")
    seconds=audio_duration(path/"audio/source_audio.m4a")
    warnings=[]; previous=0; ids=set()
    for i,x in enumerate(segments):
        if not isinstance(x,dict) or not isinstance(x.get('text'),str): raise ValueError('Invalid segment')
        start=number(x.get("start"),"start",0,7200); end=number(x.get("end"),"end",0,7200)
        reasons=[]
        if not x.get('id') or x['id'] in ids: reasons.append('Segment IDs must be unique')
        ids.add(x.get('id'))
        if end<=start: reasons.append("End must follow start")
        if i and start<previous: reasons.append("Overlapping or unsorted timing")
        if seconds and end>seconds+0.05: reasons.append("Timing exceeds audio duration")
        for word in x.get('words',[]):
            ws=number(word.get('start'),'word start',0,7200); we=number(word.get('end'),'word end',0,7200)
            if not start<=ws<we<=end: reasons.append('Word timing must fit its segment')
        previous=end
        warnings.extend({"segmentId":x.get("id",""),"index":i+1,"severity":"danger","message":r} for r in reasons)
    return {"projectId":path.name,"segments":segments,"segmentCount":len(segments),"duration":seconds or max((x["end"] for x in segments),default=0),"warnings":warnings}


@app.get("/api/projects/{project_id}/timestamps")
def timestamps(project_id: str):
    path=project_path(project_id); segments,source=timestamp_rows(path)
    return {**timing_check(path,segments),"source":source,"sourcePath":str(path/"sync/final_synced_lyrics.json"),
            "activePath":str(path/"sync/final_synced_lyrics.json"),"draftPath":str(path/"studio/timestamps_draft.json"),"hasDraft":source=="draft","versions":versions(path,"timestamps")}


@app.put("/api/projects/{project_id}/timestamps")
def save_timestamps(project_id: str, payload: dict, draft: bool = True):
    path=project_path(project_id); segments=payload.get("segments"); check=timing_check(path,segments)
    with file_lock(path/"studio/edit.lock"):
        if draft: atomic_json(path/"studio/timestamps_draft.json",segments)
        else:
            if check['warnings']: raise ValueError('Resolve timing warnings before saving current timings')
            # Current edits are kept separate until explicit approval.
            atomic_json(path/"studio/timestamps_draft.json",segments)
            save_version(path,"timestamps",segments,False)
    return timestamps(project_id)


@app.post("/api/projects/{project_id}/timestamps/validate")
def validate_timestamps(project_id: str, payload: dict):
    return timing_check(project_path(project_id),payload.get("segments"))


@app.post("/api/projects/{project_id}/timestamps/shift")
def shift_timestamps(project_id: str, payload: dict):
    segments=copy.deepcopy(payload.get("segments")); path=project_path(project_id)
    timing_check(path,segments); delta=number(payload.get("delta"),"delta",-7200,7200); ids=payload.get("segmentIds",[])
    for x in segments:
        if not ids or x['id'] in ids:
            for key in ['start','end']: x[key]=round(x[key]+delta,3)
            for word in x.get('words',[]):
                for key in ['start','end']: word[key]=round(word[key]+delta,3)
    return timing_check(path,segments)


@app.post("/api/projects/{project_id}/timestamps/approve")
def approve_timestamps(project_id: str, payload: dict):
    path=project_path(project_id); segments=payload.get("segments"); check=timing_check(path,segments)
    if check["warnings"] or not segments: raise ValueError("Resolve timing warnings before approval")
    from echoforge.core.storage import atomic_text, update_json
    from echoforge.stages.verselock.lrc_parser import seconds_to_lrc_timestamp
    with file_lock(path/"studio/edit.lock"):
        save_version(path,"timestamps",segments,True)
        atomic_json(path/"sync/final_synced_lyrics.json",{"schema":"echoforge.final_synced_lyrics.v1", "lines":[{**x,"start_seconds":x['start'],"end_seconds":x['end']} for x in segments]})
        atomic_text(path/"sync/final_synced_lyrics.lrc","\n".join(f"[{seconds_to_lrc_timestamp(x['start'])}]{x['text']}" for x in segments)+"\n")
        (path/"studio/timestamps_draft.json").unlink(missing_ok=True)
        def accept(state):
            state.setdefault('stages',{}).update(verselock='done',renderer='pending')
            state['timings_lyrics_sha256']=fingerprint(path/'lyrics/lyrics.txt') if (path/'lyrics/lyrics.txt').exists() else None
        update_json(path/'project_state.json',accept)
        # Preserve visual edits while updating only the lyric content/timing rows.
        editor=read_json(path/'editor/editor_project.json',{})
        if editor.get('schema') == 'echoforge.webeditor.v2':
            track=next((x for x in editor['tracks'] if x['type']=='text'),None)
            if track is not None:
                old={x['id']:x for x in track['clips']}
                track['clips']=[{**old.get(x['id'],{}),**x,'type':'text'} for x in segments]
                editor['revision']=editor.get('revision',0)+1
                atomic_json(path/'editor/editor_project.json',editor)
    return timestamps(project_id)


@app.get("/api/templates")
def templates():
    return [{"id":1,"name":"Classic","description":"Static lyric text on a solid background","aspectRatio":"16:9","settings":DEFAULT_DESIGN,
             "createdAt":"2026-10-09T00:00:00Z","updatedAt":"2026-10-09T00:00:00Z","isDefault":True}]


@app.get("/api/projects/{project_id}/design")
def design(project_id: str):
    path=project_path(project_id)
    return read_json(path/"studio/design.json",{"projectId":project_id,"templateId":1,"templateName":"Classic","settings":DEFAULT_DESIGN,
                                            "isSaved":False,"designPath":str(path/"studio/design.json"),"renderPropsPath":str(path/"editor/editor_project.json")})


@app.put("/api/projects/{project_id}/design")
def save_design(project_id: str, payload: dict):
    path=project_path(project_id); current=design(project_id); settings={**current['settings'],**payload.get('settings',{})}
    if settings['animation'] not in {'none','fade'}: raise ValueError('Supported animations: none, fade')
    if settings['aspectRatio'] not in {'16:9','9:16','1:1'} or settings['resolution'] not in {'720p','1080p','1440p'}: raise ValueError('Invalid aspect ratio or resolution')
    if settings['textPosition'] not in {'center','top','bottom'}: raise ValueError('Invalid text position')
    number(settings['fps'],'fps',1,60); number(settings['fontSize'],'font size',1,1000)
    for field in ['backgroundColor','textColor','highlightColor']:
        if not re.fullmatch(r'#[0-9a-fA-F]{6}',settings[field]): raise ValueError('Invalid design color')
    current.update(settings=settings,isSaved=True,updatedAt=now())
    atomic_json(path/'studio/design.json',current)
    apply_design(path,current)
    return current


def apply_design(path, current=None):
    result=make_v2_project(path)
    if not result.get('ok'): raise ValueError(result.get('reason','Editor preparation failed'))
    current=current or design(path.name); settings=current['settings']; size=int(settings['resolution'].rstrip('p'))
    w,h=(round(size*16/9),size) if settings['aspectRatio']=='16:9' else (size,round(size*16/9)) if settings['aspectRatio']=='9:16' else (size,size)
    w += w%2; h += h%2
    number(w,'width',320,3840); number(h,'height',240,2160)
    editor=read_json(path/'editor/editor_project.json'); editor['canvas']={'width':w,'height':h}
    editor['backgroundColor']=settings['backgroundColor']; editor['watermark']=settings['watermark']
    editor['settings']['fps']=settings['fps']
    for track in editor['tracks']:
        if track['type']=='image' and settings['backgroundType']=='solid': track['clips']=[]
        if track['type']=='text':
            for clip in track['clips']:
                clip.update(x=w/2,y=h*({'center':.5,'top':.15,'bottom':.85}[settings['textPosition']]),width=w*.8)
                clip.setdefault('style',{}).update(fontFamily=settings['fontFamily'],fontSize=settings['fontSize'],color=settings['textColor'],animation=settings['animation'])
    editor['revision']=editor.get('revision',0)+1
    atomic_json(path/'editor/editor_project.json',editor)


@app.get("/api/projects/{project_id}/render-readiness")
def readiness(project_id: str):
    path=project_path(project_id); summary=detail(path); state=read_json(path/'project_state.json')
    warnings=timing_check(path,timestamp_rows(path)[0])['warnings']
    checks=[{"key":key,"label":label,"ok":ok,"fix":fix} for key,label,ok,fix in [
        ('audio','Valid audio',audio_duration(path/'audio/source_audio.m4a') is not None,'Collect or normalize audio'),
        ('lyrics','Lyrics',summary['filesReady']['lyrics'],'Approve lyric text'),
        ('timestamps','Approved timings',summary['filesReady']['timestamps'] and state.get('stages',{}).get('verselock')=='done','Review and approve timings'),
        ('bounds','Timing bounds',not warnings,'Resolve timing warnings'),
        ('ffmpeg','FFmpeg',bool(shutil.which('ffmpeg')),'Install FFmpeg'),
        ('disk','Available disk space',shutil.disk_usage(path).free>256*1024*1024,'Free disk space')]]
    return {"projectId":project_id,"ready":all(c['ok'] for c in checks),"checks":checks,"warnings":warnings,
            "freeDiskBytes":shutil.disk_usage(path).free,"renderOptions":{"fps":design(project_id)['settings']['fps']}}


@app.get("/api/jobs")
def jobs(project_id: str | None = None):
    return [job_item(j) for j in render_jobs.list_jobs() if not project_id or Path(j['project_dir']).name==project_id]


@app.post("/api/projects/{project_id}/jobs/{job_type}")
def start_job(project_id: str, job_type: str, payload: dict):
    path=project_path(project_id)
    allowed={'render_preview','render_final','upload_youtube','assets_only','fetch_lyrics','run_full','continue_video'}
    if job_type not in allowed: raise ValueError('Unsupported job type')
    if job_type in {'render_preview','render_final'}:
        if not readiness(project_id)['ready']: raise HTTPException(409,'Render inputs require review')
        apply_design(path)
    options={**payload,'jobType':job_type,'upload':job_type=='upload_youtube'}
    if job_type=='render_preview': options['output']=str(path/'renders/preview_video.mp4')
    options.setdefault('fps',design(project_id)['settings']['fps'])
    if job_type=='upload_youtube':
        options.update(upload_metadata(project_id)); options['visibility']=options['privacy']
        if options.get('scheduleTime'): options.update(visibility='schedule',scheduleAt=options['scheduleTime'])
    return job_item(render_jobs.start_render_upload_job(path,options))


@app.post("/api/projects/{project_id}/actions")
def action(project_id: str, payload: dict):
    requested=payload.get('action')
    if requested=='retry': requested='continue_video'
    if requested in {'approve_lyrics','approve_sync','approve_video'}:
        raise HTTPException(409,'Open the corresponding editor to review and approve its current content')
    start_job(project_id,requested,{})
    return project(project_id)


@app.post("/api/jobs/{job_id}/cancel")
def cancel_job(job_id: int):
    jid=f'{job_id:012x}'; job=render_jobs.get_job_status(jid)
    if not job.get('job_id'): raise HTTPException(404,'Job not found')
    if job.get('stage')=='upload': raise HTTPException(409,'Remote upload is in progress; interruption could leave an uncertain result')
    render_jobs.setj(jid,cancel_requested=True)
    return job_item(render_jobs.get_job_status(jid))


@app.get("/api/projects/{project_id}/upload/metadata")
def upload_metadata(project_id: str):
    path=project_path(project_id); stored=read_json(path/'upload/youtube_metadata.json',{})
    meta=stored.get('metadata',stored); report=read_json(path/'upload/youtube_upload_report.json',{})
    return {"projectId":project_id,"title":meta.get('title',detail(path)['title']+' (Lyrics)'),"description":meta.get('description',''),"tags":meta.get('tags',[]),
            "privacy":meta.get('privacy','private'),"madeForKids":meta.get('madeForKids',meta.get('made_for_kids',False)),"playlist":meta.get('playlist',''),
            "thumbnailPath":meta.get('thumbnailPath',''),"scheduleTime":meta.get('scheduleTime',''),"metadataPath":str(path/'upload/youtube_metadata.json'),
            "publishedUrl":report.get('url','') if report.get('ok') else ''}


@app.put("/api/projects/{project_id}/upload/metadata")
def save_upload_metadata(project_id: str, payload: dict):
    path=project_path(project_id)
    if payload.get('projectId',project_id)!=project_id: raise ValueError('Metadata belongs to another project')
    if not 1<=len(payload.get('title',''))<=100: raise ValueError('Invalid title')
    if payload.get('playlist'): raise ValueError('Playlist assignment is not supported by the upload-only OAuth scope')
    if payload.get('thumbnailPath'): asset_path(path,payload['thumbnailPath'])
    if payload.get('scheduleTime'):
        privacy({'visibility':'schedule','scheduleAt':payload['scheduleTime']})
    else: privacy({'visibility':payload.get('privacy','private')})
    atomic_json(path/'upload/youtube_metadata.json',{'metadata':payload,'approved':False,'updated_at':now()})
    return upload_metadata(project_id)


@app.post("/api/projects/{project_id}/upload/metadata/generate")
def generate_metadata(project_id: str):
    from echoforge.stages.tubeharbor.metadata_generator import generate_youtube_metadata
    generate_youtube_metadata(project_path(project_id),use_gemini=False)
    return upload_metadata(project_id)


@app.post("/api/projects/{project_id}/upload/approve")
def approve_upload(project_id: str, payload: dict):
    path=project_path(project_id)
    if not nonempty(path/'renders/final_video.mp4'): raise HTTPException(409,'Render a final video first')
    metadata=save_upload_metadata(project_id,payload)
    job=start_job(project_id,'upload_youtube',{})
    return {'metadata':metadata,'job':job,'project':project(project_id)}


@app.get("/api/settings")
def settings():
    return {**DEFAULT_SETTINGS,**read_json(APP_STATE_DIR/'studio_settings.json',{})}


@app.put("/api/settings")
def save_settings(payload: dict):
    current=settings()
    allowed={'theme','defaultCountry','defaultPrivacy','autosaveSeconds','renderQuality','previewResolution'}
    current.update({k:v for k,v in payload.items() if k in allowed})
    if current['defaultCountry'] not in {'GLOBAL','US','IN','GB'} or current['defaultPrivacy'] not in {'private','public','unlisted'}: raise ValueError('Invalid defaults')
    number(current['autosaveSeconds'],'autosave seconds',1,60)
    atomic_json(APP_STATE_DIR/'studio_settings.json',current)
    return current


@app.get("/api/projects/{project_id}/media/{kind}")
def media(project_id: str, kind: str):
    path=project_path(project_id)
    names={'audio':'audio/source_audio.m4a','preview':'renders/preview_video.mp4','final':'renders/final_video.mp4'}
    if kind not in names: raise HTTPException(404,'Unknown media kind')
    file=asset_path(path,names[kind])
    if not file.is_file(): raise HTTPException(404,'Media not found')
    return FileResponse(file)


def main():
    import argparse
    import uvicorn
    parser=argparse.ArgumentParser(description='Serve EchoForge Web Studio')
    parser.add_argument('--port',type=int,default=8765)
    args=parser.parse_args()
    dist=ROOT_DIR/'apps/web-studio/frontend/dist'
    if not (dist/'index.html').exists(): raise SystemExit('Build Studio first: npm ci && npm run build in apps/web-studio/frontend')
    app.mount('/',StaticFiles(directory=dist,html=True),name='studio')
    print(f'Studio: http://127.0.0.1:{args.port}',flush=True)
    uvicorn.run(app,host='127.0.0.1',port=args.port)


if __name__=='__main__': main()
