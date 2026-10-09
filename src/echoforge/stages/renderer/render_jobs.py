
from __future__ import annotations
import threading, traceback, uuid
from pathlib import Path
from echoforge.stages.renderer.exporter import export_editor_project
from echoforge.stages.tubeharbor.youtube_uploader import upload_to_youtube
from echoforge.core.paths import ROOT_DIR

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from echoforge.core.storage import atomic_json, file_lock, read_json
from echoforge.stages.tubeharbor.youtube_uploader import privacy

_JOBS = {}
_LOCK = threading.RLock()
_JOBS_FILE = ROOT_DIR / 'data/render_jobs.json'
_SESSION = uuid.uuid4().hex
_EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="echoforge-job")
_ACTIVE_STATUSES = {'queued', 'running', 'rendering', 'uploading'}


def now():
    return datetime.now(timezone.utc).isoformat()


def _owner_alive(job):
    pid = job.get('owner_pid')
    if not pid: return False
    if pid == os.getpid(): return job.get('owner_session') == _SESSION
    try:
        os.kill(int(pid), 0)
        return True
    except ProcessLookupError: return False
    except PermissionError: return True
    except OSError: return False


def _load_jobs():
    global _JOBS
    _JOBS = read_json(_JOBS_FILE, {})
    if not isinstance(_JOBS, dict): raise ValueError('Invalid render job registry')
    for job in _JOBS.values():
        if job.get('status') in _ACTIVE_STATUSES and not _owner_alive(job):
            job.update(ok=False, status='interrupted', stage='interrupted', progress=1,
                       reason='Worker exited before completion; render may be retried. Upload ledger guards uncertain inserts.', updated_at=now())
    return _JOBS


def _save_jobs():
    atomic_json(_JOBS_FILE, _JOBS)


def _mutate(callback):
    with _LOCK, file_lock(_JOBS_FILE.with_suffix('.lock')):
        _load_jobs()
        result = callback(_JOBS)
        _save_jobs()
        return result


def setj(jid, **kw):
    def change(jobs):
        jobs[jid].update(**kw, updated_at=now())
    _mutate(change)


def log(jid, msg):
    def change(jobs):
        logs=jobs[jid].setdefault('logs', [])
        logs.append({'time':now(), 'message':msg})
        del logs[:-200]
    _mutate(change)


def get_job_status(job_id):
    return _mutate(lambda jobs: dict(jobs.get(job_id) or {'ok':False, 'reason':'Unknown job', 'job_id':job_id}))


def list_jobs():
    return _mutate(lambda jobs: [dict(j) for j in jobs.values()])


def project_job_status(project):
    jobs=[j for j in list_jobs() if j.get('project_dir') == str(Path(project).resolve())]
    if not jobs:
        return {'ok':None, 'running':False, 'stage':'idle', 'phase':'idle', 'status':'idle', 'progress':0}
    job=max(jobs, key=lambda j:j.get('created_at', ''))
    return {**job, 'running':job.get('status') in _ACTIVE_STATUSES,
            'phase':job.get('stage'), 'progress':round(float(job.get('progress', 0))*100),
            'message':job.get('reason') or (job.get('logs') or [{}])[-1].get('message', ''),
            'rendered_video':job.get('output'), 'youtube_url':(job.get('youtube') or {}).get('url')}


def normalize_options(options):
    if not isinstance(options, dict): raise ValueError('Job options must be an object')
    merged={**(options.get('metadata') or {}), **options}
    for canonical, aliases in {'scheduleAt':['schedule_at','schedule_time','scheduleTime','publishAt'],
                               'categoryId':['category_id'], 'madeForKids':['made_for_kids']}.items():
        for alias in aliases:
            if not merged.get(canonical) and merged.get(alias) is not None:
                merged[canonical]=merged[alias]
    from echoforge.core.security import number
    merged['fps']=int(number(merged.get('fps', 24), 'fps', 1, 60))
    merged['crf']=int(number(merged.get('crf', 20), 'crf', 0, 51))
    if not isinstance(merged.get('upload', False), bool): raise ValueError('upload must be boolean')
    merged.setdefault('upload', False)
    if merged['upload']: privacy(merged)
    return merged


def start_render_upload_job(project_dir, options, *, background=True):
    project=Path(project_dir).resolve()
    options=normalize_options(options)
    def queue(jobs):
        for existing in jobs.values():
            if existing.get('project_dir') == str(project) and existing.get('status') in _ACTIVE_STATUSES:
                return {**existing, 'already_running':True}
        if sum(j.get('status') in _ACTIVE_STATUSES for j in jobs.values()) >= 50:
            raise ValueError('Job queue is full; wait for active jobs to finish')
        jid=uuid.uuid4().hex[:12]
        job={'ok':True, 'job_id':jid, 'status':'queued', 'stage':'queued', 'progress':0,
             'project_dir':str(project), 'options':options, 'owner_pid':os.getpid(), 'owner_session':_SESSION,
             'created_at':now(), 'updated_at':now(), 'logs':[{'time':now(), 'message':'Render job queued'}]}
        jobs[jid]=job
        return dict(job)
    job=_mutate(queue)
    if not job.get('already_running'):
        if background:
            try:
                _EXECUTOR.submit(run, job['job_id'], project, options)
            except Exception as exc:
                setj(job['job_id'], ok=False, status='failed', reason=str(exc))
                raise
        else:
            run(job['job_id'], project, options)
            return get_job_status(job['job_id'])
    return job

def run(jid, project, options):
    try:
        setj(jid,status="running",stage="render",progress=.01); log(jid,"Starting render")
        def cb(p):
            if get_job_status(jid).get('cancel_requested'): raise InterruptedError('Job cancelled')
            setj(jid,status="running",stage=p.get("stage","render"),progress=max(0,min(float(p.get("progress",0) or 0),.97)))
            if p.get("message"): log(jid,str(p.get("message")))
        kind=options.get('jobType', 'render_final')
        if get_job_status(jid).get('cancel_requested'): raise InterruptedError('Job cancelled')
        if kind in {'assets_only','fetch_lyrics','run_full','continue_video'}:
            if kind != 'continue_video':
                from echoforge.stages.musevault.asset_collector import collect_assets
                cb({'stage':'assets', 'message':'Collecting project assets', 'progress':.05})
                result=collect_assets(project, auto_review=True)
                if not result.get('ok'): raise RuntimeError(result.get('reason', 'Asset collection failed'))
            if kind in {'run_full','continue_video'}:
                from echoforge.stages.verselock.sync_runner import run_verselock_sync
                cb({'stage':'sync', 'message':'Preparing lyric timings', 'progress':.5})
                result=run_verselock_sync(project)
                if not result.get('ok'):
                    setj(jid, ok=False,status='needs_review',stage='sync',progress=1,reason=result.get('reason'),result=result)
                    return
            setj(jid,ok=True,status='completed',stage='done',progress=1)
            return
        if kind == 'upload_youtube':
            video=project / 'renders/final_video.mp4'
            if not video.is_file(): raise FileNotFoundError('Final video is missing')
            render={'ok':True,'output':str(video)}
        else:
            render=export_editor_project(project, options.get("output"), int(options.get("fps") or 24), int(options.get("crf") or 20), cb); setj(jid,render=render)
        if not render.get("ok"):
            setj(jid,ok=False,status="failed",stage="render",progress=1,reason=render.get("reason","Render failed")); log(jid,"Render failed: "+str(render.get("reason"))); return
        video=render.get("output"); log(jid,"Render finished: "+str(video))
        if not bool(options.get("upload", True)):
            setj(jid,ok=True,status="completed",stage="done",progress=1,output=video,upload=None); log(jid,"Upload skipped"); return
        if get_job_status(jid).get("cancel_requested"): raise InterruptedError("Job cancelled")
        setj(jid,status="running",stage="upload",progress=.97); log(jid,"Starting YouTube upload")
        def ucb(p):
            if p.get("progress") is not None: setj(jid,stage="upload",progress=.97+.03*max(0,min(float(p.get("progress")),1)))
            if p.get("message"): log(jid,str(p.get("message")))
        upload=upload_to_youtube(video, project, options, ucb); setj(jid,upload=upload)
        if not upload.get("ok"):
            setj(jid,ok=False,status="upload_failed",stage="upload",progress=1,output=video,reason=upload.get("reason","Upload failed")); log(jid,"Upload failed: "+str(upload.get("reason"))); return
        setj(jid,ok=True,status="completed",stage="done",progress=1,output=video,youtube=upload); log(jid,"Render and upload complete")
    except InterruptedError as e:
        setj(jid,ok=False,status='cancelled',stage='cancelled',progress=1,reason=str(e))
    except Exception as e:
        setj(jid,ok=False,status="failed",progress=1,reason=str(e),traceback=traceback.format_exc()); log(jid,"Job failed: "+str(e))
