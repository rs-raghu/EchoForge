
from __future__ import annotations
import json, os
from datetime import datetime, timezone, timedelta
from echoforge.core.storage import atomic_json, file_lock
from echoforge.core.project_state import mark_uploaded
from echoforge.core.media import fingerprint
from pathlib import Path
from echoforge.stages.tubeharbor import upload_db
SCOPES=["https://www.googleapis.com/auth/youtube.upload"]
def emit(cb, **kw):
    if cb: cb(kw)
def read_json(p, d=None): return json.loads(p.read_text(encoding="utf-8")) if p.exists() else d
def root(project_dir):
    try: return project_dir.parents[1]
    except Exception: return Path.cwd()
def cred_paths(project_dir):
    r=root(project_dir); sec=r/".secrets"; env=os.environ.get("YOUTUBE_CLIENT_SECRET_PATH") or os.environ.get("YOUTUBE_CLIENT_SECRET_FILE"); cand=[]
    if env: cand.append(Path(env))
    cand += [sec/"youtube_client_secret.json", r/"assets/youtube/client_secret.json", r/"client_secret.json"]
    return next((p for p in cand if p.exists()), sec/"youtube_client_secret.json"), Path(os.environ.get("YOUTUBE_TOKEN_PATH") or os.environ.get("YOUTUBE_TOKEN_FILE") or sec/"youtube_token.json")
def meta(project_dir): return {"state":read_json(project_dir/"project_state.json",{}) or {}, "review":read_json(project_dir/"metadata_review.json",{}) or {}}
def title(project_dir, options):
    if options.get("title"): return str(options["title"]).strip()
    m=meta(project_dir); r=m["review"]; s=m["state"]; t=r.get("display_title") or r.get("title") or s.get("title") or s.get("song_title") or project_dir.name; a=r.get("display_artist") or r.get("artist") or s.get("artist") or s.get("artist_text") or ""
    return f"{t} - {a} (Lyrics)" if a else f"{t} (Lyrics)"
def desc(project_dir, options):
    if options.get("description"): return str(options["description"])
    return title(project_dir,{}).replace(" (Lyrics)", "")+" lyrics video.\n\nGenerated with EchoForge."
def tags(options):
    raw=options.get("tags")
    if isinstance(raw,list): return [str(x).strip() for x in raw if str(x).strip()]
    if isinstance(raw,str): return [x.strip() for x in raw.split(",") if x.strip()]
    return ["lyrics","lyric video","music"]
def thumb(project_dir, options):
    for p in [project_dir/"renders/upload_thumbnail.jpg", project_dir/"images/upload_thumbnail.jpg", project_dir/"thumbnail.jpg"]:
        if p.exists(): return p
    return None
def privacy(options, now=None):
    v=str(options.get("visibility") or options.get("privacyStatus") or "private").lower().strip()
    if v not in {'public', 'private', 'unlisted', 'schedule', 'scheduled'}:
        raise ValueError('Invalid visibility')
    pub=options.get('scheduleAt') or options.get('schedule_at') or options.get('schedule_time') or options.get('publishAt')
    if v in {'schedule', 'scheduled'} or pub:
        if not pub:
            raise ValueError('Scheduling requires a timezone-aware future timestamp')
        when=datetime.fromisoformat(str(pub).replace('Z', '+00:00'))
        if when.tzinfo is None or when.utcoffset() is None:
            raise ValueError('Schedule timestamp must include a timezone offset')
        if when <= (now or datetime.now(timezone.utc)) + timedelta(minutes=1):
            raise ValueError('Schedule timestamp must be at least one minute in the future')
        return 'private', when.astimezone(timezone.utc).isoformat()
    return v, None

def service(project_dir):
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build
    except Exception as e: return None, {"ok":False,"reason":"Missing Google upload dependencies. Run: pip install google-api-python-client google-auth-oauthlib google-auth-httplib2","error":str(e)}
    cs,tp=cred_paths(project_dir)
    if not cs.exists(): return None, {"ok":False,"reason":"Missing YouTube OAuth client secret file.","expected":[str(root(project_dir)/".secrets/youtube_client_secret.json"), str(root(project_dir)/"assets/youtube/client_secret.json")],"setup":"Save OAuth desktop client as .secrets/youtube_client_secret.json"}
    tp.parent.mkdir(parents=True, exist_ok=True); creds=None
    if tp.exists(): creds=Credentials.from_authorized_user_file(str(tp), SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token: creds.refresh(Request())
        else:
            flow=InstalledAppFlow.from_client_secrets_file(str(cs), SCOPES); creds=flow.run_local_server(port=0)
        tp.write_text(creds.to_json(), encoding="utf-8")
    return build("youtube","v3",credentials=creds), None
def upload_to_youtube(video_path, project_dir, options, progress_callback=None):
    project=Path(project_dir).resolve(); video=Path(video_path).resolve()
    # OS ownership makes duplicate requests serialize, including across CLI/editor workers.
    with file_lock(project / 'upload' / 'youtube_insert.lock', timeout=3600):
        existing=upload_db.get_upload(project)
        report=read_json(project / 'upload/youtube_upload_report.json', {})
        known=existing if existing and existing.get('ok') and existing.get('video_id') else report
        if known and known.get('ok') and known.get('video_id'):
            upload_db.record_upload(project, known)
            try:
                mark_uploaded(project, known)
            except Exception as exc:
                known={**known, 'state_warning': str(exc)}
            return {**known, 'reused_existing_upload': True}
        if existing and existing.get('status') in {'uploading', 'uncertain'}:
            return {'ok': False, 'stage':'upload', 'reason':'Prior upload outcome is uncertain. Reconcile its remote video ID before retrying.', 'requires_reconciliation': True}
        if not video.is_file() or not video.stat().st_size:
            return {'ok':False, 'stage':'upload', 'reason':'Rendered video is missing or empty'}
        priv,pub=privacy(options)
        stored=read_json(project / 'upload/youtube_metadata.json', {}) or {}
        meta=stored.get('metadata', stored)
        approved=options.get('metadata') or {}
        combined={**meta, **approved, **{k:v for k,v in options.items() if v is not None}}
        body={'snippet':{'title': title(project, combined), 'description': combined.get('description', desc(project, combined)),
                         'tags':tags(combined), 'categoryId':str(combined.get('categoryId') or combined.get('category_id') or '10')},
              'status':{'privacyStatus':priv, 'selfDeclaredMadeForKids':bool(combined.get('madeForKids', combined.get('made_for_kids', False)))}}
        if not 1 <= len(body['snippet']['title']) <= 100:
            raise ValueError('YouTube title must contain 1 to 100 characters')
        if len(body['snippet']['description'].encode('utf-8')) > 5000:
            raise ValueError('YouTube description exceeds 5000 bytes')
        if pub: body['status']['publishAt']=pub
        yt,err=service(project)
        if err: return err
        from googleapiclient.http import MediaFileUpload
        record={'ok':False, 'status':'uploading', 'video_sha256':fingerprint(video), 'started_at':datetime.now(timezone.utc).isoformat()}
        upload_db.record_upload(project, record)
        try:
            emit(progress_callback,stage='upload',message='Uploading video to YouTube',progress=0)
            req=yt.videos().insert(part='snippet,status',body=body,media_body=MediaFileUpload(str(video),chunksize=8*1024*1024,resumable=True,mimetype='video/mp4'))
            response=None
            while response is None:
                st,response=req.next_chunk()
                if st: emit(progress_callback,stage='upload',message='Uploading video',progress=st.progress())
            vid=response.get('id') if isinstance(response, dict) else None
            if not isinstance(vid, str) or not vid.strip():
                raise ValueError('YouTube returned no video ID')
            res={'ok':True, 'status':'uploaded', 'stage':'upload', 'video_id':vid, 'url':f'https://www.youtube.com/watch?v={vid}',
                 'privacyStatus':priv, 'publishAt':pub, 'metadata':body, 'video_sha256':record['video_sha256'], 'uploaded_at':datetime.now(timezone.utc).isoformat()}
            # Persist remote success before optional thumbnail/state work. Never retry insert after these fail.
            upload_db.record_upload(project, res)
            atomic_json(project / 'upload/youtube_upload_report.json', res)
        except Exception as exc:
            upload_db.record_upload(project, {**record, 'status':'uncertain', 'reason':str(exc)})
            return {'ok':False, 'stage':'upload', 'reason':str(exc), 'requires_reconciliation':True}
        th=Path(combined['thumbnail']) if combined.get('thumbnail') else thumb(project, combined)
        if th and th.is_file():
            try:
                yt.thumbnails().set(videoId=vid,media_body=MediaFileUpload(str(th))).execute()
                res['thumbnail_uploaded']=True
            except Exception as exc:
                res.update(thumbnail_uploaded=False, thumbnail_error=str(exc))
        try:
            mark_uploaded(project, res)
        except Exception as exc:
            res['state_warning']=str(exc)
        atomic_json(project / 'upload/youtube_upload_report.json', res)
        upload_db.record_upload(project, res)
        emit(progress_callback,stage='upload',message='YouTube upload complete',progress=1)
        return res
