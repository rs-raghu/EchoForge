
from __future__ import annotations
import json, os
from pathlib import Path
from typing import Any, Callable, Dict, Optional
SCOPES=["https://www.googleapis.com/auth/youtube.upload"]
def emit(cb, **kw):
    if cb: cb(kw)
def read_json(p, d=None): return json.loads(p.read_text(encoding="utf-8")) if p.exists() else d
def root(project_dir):
    try: return project_dir.parents[1]
    except Exception: return Path.cwd()
def cred_paths(project_dir):
    r=root(project_dir); sec=r/".secrets"; env=os.environ.get("YOUTUBE_CLIENT_SECRET_FILE"); cand=[]
    if env: cand.append(Path(env))
    cand += [sec/"youtube_client_secret.json", r/"assets/youtube/client_secret.json", r/"client_secret.json"]
    return next((p for p in cand if p.exists()), sec/"youtube_client_secret.json"), Path(os.environ.get("YOUTUBE_TOKEN_FILE", sec/"youtube_token.json"))
def meta(project_dir): return {"state":read_json(project_dir/"project_state.json",{}) or {}, "review":read_json(project_dir/"metadata_review.json",{}) or {}}
def title(project_dir, options):
    if options.get("title"): return str(options["title"]).strip()
    m=meta(project_dir); r=m["review"]; s=m["state"]; t=r.get("display_title") or r.get("title") or s.get("song_title") or project_dir.name; a=r.get("display_artist") or r.get("artist") or s.get("artist_text") or ""
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
def privacy(options):
    v=str(options.get("visibility") or options.get("privacyStatus") or "private").lower().strip(); pub=options.get("scheduleAt") or options.get("publishAt")
    if v in ("schedule","scheduled"): return "private", str(pub).strip() if pub else None
    return (v if v in ("public","private","unlisted") else "private"), str(pub).strip() if pub else None
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
    if not video.exists(): return {"ok":False,"stage":"upload","reason":"Video file not found: "+str(video)}
    yt,err=service(project)
    if err: return err
    try: from googleapiclient.http import MediaFileUpload
    except Exception as e: return {"ok":False,"stage":"upload","reason":"Missing googleapiclient MediaFileUpload","error":str(e)}
    priv,pub=privacy(options); body={"snippet":{"title":title(project,options),"description":desc(project,options),"tags":tags(options),"categoryId":str(options.get("categoryId") or "10")},"status":{"privacyStatus":priv,"selfDeclaredMadeForKids":bool(options.get("madeForKids",False))}}
    if pub: body["status"]["publishAt"]=pub
    emit(progress_callback,stage="upload",message="Uploading video to YouTube",progress=0)
    req=yt.videos().insert(part="snippet,status",body=body,media_body=MediaFileUpload(str(video),chunksize=8*1024*1024,resumable=True,mimetype="video/mp4")); response=None
    while response is None:
        st,response=req.next_chunk()
        if st: emit(progress_callback,stage="upload",message=f"YouTube upload {int(st.progress()*100)}%",progress=st.progress())
    vid=response.get("id"); res={"ok":True,"stage":"upload","video_id":vid,"url":f"https://www.youtube.com/watch?v={vid}" if vid else None,"privacyStatus":priv,"publishAt":pub,"title":body["snippet"]["title"]}
    th=thumb(project,options)
    if th and vid:
        try: yt.thumbnails().set(videoId=vid,media_body=MediaFileUpload(str(th))).execute(); res["thumbnail_uploaded"]=True
        except Exception as e: res["thumbnail_uploaded"]=False; res["thumbnail_error"]=str(e)
    out=project/"upload/youtube_upload_report.json"; out.parent.mkdir(parents=True, exist_ok=True); out.write_text(json.dumps(res,indent=2,ensure_ascii=False),encoding="utf-8"); emit(progress_callback,stage="upload",message="YouTube upload complete",progress=1); return res
