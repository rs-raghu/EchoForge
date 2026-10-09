
from __future__ import annotations

from echoforge.core.storage import atomic_text
import json
from datetime import datetime, timezone, timedelta
from echoforge.core.storage import atomic_json, file_lock
from echoforge.core.project_state import mark_uploaded
from echoforge.core.media import fingerprint
from pathlib import Path
from echoforge.stages.tubeharbor import upload_db
from echoforge.stages.tubeharbor.upload_options import FIELDS, normalize_upload_options, resolve_upload_options, persist_upload_options
SCOPES=["https://www.googleapis.com/auth/youtube.upload"]
def emit(cb, **kw):
    if cb: cb(kw)
def read_json(p, d=None): return json.loads(p.read_text(encoding="utf-8")) if p.exists() else d
def root(project_dir):
    try: return project_dir.parents[1]
    except Exception: return Path.cwd()
def cred_paths(project_dir):
    from echoforge.core.config import Settings
    config=Settings(); sec=root(project_dir)/'.secrets'
    return config.youtube_client_secret_path or sec/'youtube_client_secret.json', config.youtube_token_path or sec/'youtube_token.json'

def meta(project_dir): return {"state":read_json(project_dir/"project_state.json",{}) or {}, "review":read_json(project_dir/"metadata_review.json",{}) or {}}
def title(project_dir, options):
    if 'title' in options: return str(options['title']).strip()
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
    selected=options.get('thumbnail') or options.get('thumbnailPath') or options.get('thumbnail_path')
    if selected:
        from echoforge.core.security import asset_path
        path=asset_path(project_dir, selected)
        if path.suffix.lower() not in {'.jpg','.jpeg','.png'} or not path.is_file():
            raise ValueError('Thumbnail must be an existing project or shared JPEG/PNG asset')
        return path
    for p in [project_dir/"renders/upload_thumbnail.jpg", project_dir/"images/upload_thumbnail.jpg", project_dir/"thumbnail.jpg"]:
        if p.exists(): return p
    return None
def privacy(options, now=None):
    options=normalize_upload_options(options)
    v=str(options.get("visibility") or "private").lower().strip()
    if v not in {'public', 'private', 'unlisted', 'schedule', 'scheduled'}:
        raise ValueError('Invalid visibility')
    pub=options.get('scheduleAt')
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
        atomic_text(tp, creds.to_json())
    import httplib2
    from google_auth_httplib2 import AuthorizedHttp
    http=AuthorizedHttp(creds,http=httplib2.Http(timeout=60))
    return build("youtube","v3",http=http,cache_discovery=False), None
def upload_to_youtube(video_path, project_dir, options, progress_callback=None):
    project=Path(project_dir).resolve(); video=Path(video_path).resolve()
    # OS ownership makes duplicate requests serialize, including across CLI/editor workers.
    with file_lock(project / 'upload' / 'youtube_insert.lock', timeout=3600):
        combined=resolve_upload_options(project, options)
        existing=upload_db.get_upload(project)
        report=read_json(project / 'upload/youtube_upload_report.json', {})
        known=existing if existing and existing.get('ok') and existing.get('video_id') else report
        if known and known.get('ok') and known.get('video_id'):
            # A duplicate request may reuse success; changed content must never look
            # like a successful update of a video that YouTube already received.
            changed_video=video.is_file() and known.get('video_sha256') and fingerprint(video)!=known['video_sha256']
            unverifiable_video=video.is_file() and not known.get('video_sha256')
            previous=known.get('metadata') or {}
            snippet=previous.get('snippet', {})
            status=previous.get('status', {})
            prior={'title':snippet.get('title'), 'description':snippet.get('description'),
                   'tags':snippet.get('tags'), 'categoryId':snippet.get('categoryId'),
                   'madeForKids':status.get('selfDeclaredMadeForKids'),
                   'visibility':status.get('privacyStatus'), 'scheduleAt':status.get('publishAt') or ''}
            changed_fields=[]
            for key in FIELDS & combined.keys():
                if key=='thumbnailPath':
                    selected=thumb(project, combined)
                    if selected and fingerprint(selected)!=known.get('thumbnail_sha256'): changed_fields.append(key)
                    continue
                value=combined[key]
                if key=='tags': value=tags(combined)
                if key=='categoryId': value=str(value)
                if key=='title': value=str(value).strip()
                if key=='visibility': value=str(value).lower().strip()
                if key=='scheduleAt' and value:
                    when=datetime.fromisoformat(str(value).replace('Z','+00:00'))
                    if when.tzinfo is None or when.utcoffset() is None:
                        raise ValueError('Schedule timestamp must include a timezone offset')
                    value=when.astimezone(timezone.utc).isoformat()
                if key=='visibility' and combined.get('scheduleAt'): value='private'
                if value!=prior.get(key): changed_fields.append(key)
            if changed_video or unverifiable_video or changed_fields:
                return {'ok':False, 'stage':'upload', 'reason':
                        'This project already has a YouTube video. Your changes were not applied to it. '
                        + ('YouTube cannot replace its video file; publish the edited render as a new project/video. ' if changed_video else '')
                        + ('The historical upload has no video fingerprint, so this render cannot be verified against it. Review the existing upload before publishing a new project/video. ' if unverifiable_video else '')
                        + ('Edit existing video settings in YouTube Studio; this upload action does not update published metadata.' if changed_fields else ''),
                        'existing_video_id':known['video_id'], 'existing_video_url':known.get('url'),
                        'changed_fields':sorted(changed_fields), 'video_changed':bool(changed_video)}
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
        priv,pub=privacy(combined)
        th=thumb(project, combined)
        thumbnail_sha256=fingerprint(th) if th else None
        kids=combined.get('madeForKids', combined.get('made_for_kids', False))
        if not isinstance(kids,bool): raise ValueError('madeForKids must be boolean')
        body={'snippet':{'title': title(project, combined), 'description': combined.get('description', desc(project, combined)),
                         'tags':tags(combined), 'categoryId':str(combined.get('categoryId') or combined.get('category_id') or '10')},
              'status':{'privacyStatus':priv, 'selfDeclaredMadeForKids':kids}}
        if not 1 <= len(body['snippet']['title']) <= 100:
            raise ValueError('YouTube title must contain 1 to 100 characters')
        if len(body['snippet']['description'].encode('utf-8')) > 5000:
            raise ValueError('YouTube description exceeds 5000 bytes')
        if pub: body['status']['publishAt']=pub
        persist_upload_options(project, combined)
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
            if thumbnail_sha256: res['thumbnail_sha256']=thumbnail_sha256
            # Persist remote success before optional thumbnail/state work. Never retry insert after these fail.
            upload_db.record_upload(project, res)
            atomic_json(project / 'upload/youtube_upload_report.json', res)
        except Exception as exc:
            upload_db.record_upload(project, {**record, 'status':'uncertain', 'reason':str(exc)})
            return {'ok':False, 'stage':'upload', 'reason':str(exc), 'requires_reconciliation':True}
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
