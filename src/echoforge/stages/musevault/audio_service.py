from __future__ import annotations
import os
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from echoforge.core.media import audio_duration, fingerprint
from echoforge.core.storage import atomic_json, read_json, file_lock


def now_iso(): return datetime.now(timezone.utc).isoformat()


def find_audio(audio_dir):
    return next((p for p in sorted(Path(audio_dir).glob('*')) if p.suffix.lower() in {'.m4a','.mp3','.webm','.opus','.wav','.aac'} and audio_duration(p)), None)


def download_audio(project_dir, review):
    folder=Path(project_dir)/'audio'; folder.mkdir(parents=True,exist_ok=True)
    status=folder/'audio_status.json'; url=str(review.get('youtube_url') or '').strip()
    if not url: return {'ok':False,'status':'failed','reason':'missing YouTube URL'}
    with file_lock(folder/'download.lock',timeout=3600):
        previous=read_json(status,{})
        existing=folder/'source_audio.m4a'
        if previous.get('ok') and previous.get('youtube_url')==url and audio_duration(existing) and previous.get('sha256')==fingerprint(existing):
            return {**previous,'status':'exists','path':str(existing)}
        result={'ok':False,'status':'failed','youtube_url':url,'checked_at':now_iso()}
        try:
            import yt_dlp
            with tempfile.TemporaryDirectory(prefix='.download-',dir=folder) as td:
                work=Path(td)
                options={'format':'bestaudio[ext=m4a]/bestaudio/best','outtmpl':str(work/'source_audio.%(ext)s'),
                         'noplaylist':True,'retries':3,'fragment_retries':3,'socket_timeout':30}
                with yt_dlp.YoutubeDL(options) as ydl: info=ydl.extract_info(url,download=True)
                source=find_audio(work)
                if not source: raise ValueError('Download contains no valid audio stream')
                target=work/'normalized.m4a'
                subprocess.run(['ffmpeg','-v','error','-y','-i',str(source),'-vn','-c:a','aac','-b:a','192k',str(target)],check=True,capture_output=True,timeout=1800)
                if not audio_duration(target): raise ValueError('Normalized download is invalid')
                os.replace(target,existing)
                result.update(ok=True,status='downloaded',path=str(existing),sha256=fingerprint(existing),title=info.get('title') if isinstance(info,dict) else None)
        except Exception as exc:
            result['reason']=str(exc)
        atomic_json(status,result)
        return result
