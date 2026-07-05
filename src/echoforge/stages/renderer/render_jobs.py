
from __future__ import annotations
import threading, time, traceback, uuid
from pathlib import Path
from typing import Any, Dict
from echoforge.stages.renderer.exporter import export_editor_project
from echoforge.stages.tubeharbor.youtube_uploader import upload_to_youtube
_JOBS: Dict[str, Dict[str, Any]] = {}; _LOCK=threading.Lock()
def now(): return time.strftime("%Y-%m-%dT%H:%M:%S%z")
def setj(jid, **kw):
    with _LOCK:
        j=_JOBS.setdefault(jid,{}); j.update(kw); j["updated_at"]=now()
def log(jid,msg):
    with _LOCK:
        j=_JOBS.setdefault(jid,{}); logs=j.setdefault("logs",[]); logs.append({"time":now(),"message":msg}); del logs[:-200]; j["updated_at"]=now()
def get_job_status(job_id):
    with _LOCK:
        return dict(_JOBS.get(job_id) or {"ok":False,"reason":"Unknown job","job_id":job_id})
# ef_single_project_job_guard
_ACTIVE_STATUSES = {"queued", "running", "rendering", "uploading"}

def start_render_upload_job(project_dir, options):
    project = Path(project_dir).resolve()
    with _LOCK:
        for existing_id, existing in _JOBS.items():
            same_project = str(existing.get("project_dir")) == str(project)
            active = str(existing.get("status", "")).lower() in _ACTIVE_STATUSES
            if same_project and active:
                copy = dict(existing)
                copy["already_running"] = True
                copy["reason"] = "A render/upload job is already running for this project. Wait for it to finish before starting another."
                return copy

        jid = uuid.uuid4().hex[:12]
        _JOBS[jid] = {
            "ok": True,
            "job_id": jid,
            "status": "queued",
            "stage": "queued",
            "progress": 0,
            "project_dir": str(project),
            "options": options,
            "logs": [{"time": now(), "message": "Render job queued"}],
            "created_at": now(),
            "updated_at": now(),
        }
    threading.Thread(target=run, args=(jid, project, options), daemon=True).start()
    return get_job_status(jid)

def run(jid, project, options):
    try:
        setj(jid,status="running",stage="render",progress=.01); log(jid,"Starting render")
        def cb(p):
            setj(jid,status="running",stage=p.get("stage","render"),progress=max(0,min(float(p.get("progress",0) or 0),.97)))
            if p.get("message"): log(jid,str(p.get("message")))
        render=export_editor_project(project, options.get("output"), int(options.get("fps") or 24), int(options.get("crf") or 20), cb); setj(jid,render=render)
        if not render.get("ok"):
            setj(jid,ok=False,status="failed",stage="render",progress=1,reason=render.get("reason","Render failed")); log(jid,"Render failed: "+str(render.get("reason"))); return
        video=render.get("output"); log(jid,"Render finished: "+str(video))
        if not bool(options.get("upload", True)):
            setj(jid,ok=True,status="completed",stage="done",progress=1,output=video,upload=None); log(jid,"Upload skipped"); return
        setj(jid,status="running",stage="upload",progress=.97); log(jid,"Starting YouTube upload")
        def ucb(p):
            if p.get("progress") is not None: setj(jid,stage="upload",progress=.97+.03*max(0,min(float(p.get("progress")),1)))
            if p.get("message"): log(jid,str(p.get("message")))
        upload=upload_to_youtube(video, project, options, ucb); setj(jid,upload=upload)
        if not upload.get("ok"):
            setj(jid,ok=False,status="upload_failed",stage="upload",progress=1,output=video,reason=upload.get("reason","Upload failed")); log(jid,"Upload failed: "+str(upload.get("reason"))); return
        setj(jid,ok=True,status="completed",stage="done",progress=1,output=video,youtube=upload); log(jid,"Render and upload complete")
    except Exception as e:
        setj(jid,ok=False,status="failed",progress=1,reason=str(e),traceback=traceback.format_exc()); log(jid,"Job failed: "+str(e))
