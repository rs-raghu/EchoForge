import json
import threading
from http.server import ThreadingHTTPServer
from unittest.mock import Mock
import requests
import pytest
from PIL import Image
from echoforge.core.storage import atomic_json
from echoforge.core.security import asset_path
from echoforge.stages.renderer import server, exporter


@pytest.fixture
def http_editor(tmp_path,monkeypatch):
    project=tmp_path/'projects/fixture'; project.mkdir(parents=True)
    monkeypatch.setattr(server,'PROJECT_DIR',project,raising=False)
    monkeypatch.setattr(server,'ROOT_DIR',tmp_path)
    atomic_json(project/'editor/editor_project.json',{'schema':'echoforge.webeditor.v2','canvas':{'width':320,'height':240},'project':{'title':'Fixture','duration':.2},'assets':{},'tracks':[{'id':'lyrics','type':'text','clips':[{'id':'l1','type':'text','start':0,'end':.2,'text':'Hello','x':50,'y':120}]}]})
    http=ThreadingHTTPServer(('127.0.0.1',0),server.Handler)
    thread=threading.Thread(target=http.serve_forever); thread.start()
    try: yield project,'http://127.0.0.1:'+str(http.server_port)
    finally: http.shutdown(); thread.join(); http.server_close()


def test_root_secret_denied_and_save_revision(http_editor):
    project,url=http_editor
    (project.parent.parent/'.env').write_text('DUMMY_SECRET')
    assert requests.get(url+'/root/.env',timeout=5).status_code==403
    payload=requests.get(url+'/api/project',timeout=5).json()
    assert requests.post(url+'/api/project',json=payload,timeout=5).json()['revision']==1
    assert requests.post(url+'/api/project',json=payload,timeout=5).status_code==409
    payload['assets']['audio']='../../outside.wav'
    assert requests.post(url+'/api/project',json=payload,timeout=5).status_code==400


def test_single_render_contract_all_aliases(http_editor,monkeypatch):
    project,url=http_editor
    start=Mock(return_value={'ok':True,'job_id':'fixture'})
    monkeypatch.setattr(server,'start_render_upload_job',start)
    body={'upload':True,'visibility':'public','metadata':{'title':'Approved'},'schedule_at':''}
    for route in ['/api/render/start','/api/render-upload/start','/api/render-upload-start']:
        assert requests.post(url+route,json=body,timeout=5).status_code==200
        assert start.call_args.args==(project,body)


def test_media_range_and_private_paths(http_editor):
    project,url=http_editor
    audio=project/'audio/source_audio.m4a'; audio.parent.mkdir(); audio.write_bytes(b'0123456789')
    response=requests.get(url+'/media/audio/source_audio.m4a',headers={'Range':'bytes=-3'},timeout=5)
    assert response.status_code==206 and response.content==b'789'
    assert requests.get(url+'/media/audio/source_audio.m4a',headers={'Range':'bytes=99-'},timeout=5).status_code==416
    secret=project/'.secrets/token.mp4'; secret.parent.mkdir(); secret.write_text('DUMMY')
    with pytest.raises(ValueError): asset_path(project,'.secrets/token.mp4')


def test_real_render_honors_background_and_deleted_audio(http_editor):
    project,url=http_editor
    background=project/'images/red.png'; background.parent.mkdir(); Image.new('RGB',(320,240),'red').save(background)
    data={'stage':'renderer_stage1_editor_project','canvas':{'width':320,'height':240},'assets':{'background':'images/red.png'},'clips':[{'type':'text','start':0,'end':.2,'text':'','x':50,'y':120}]}
    atomic_json(project/'editor/editor_project.json',data)
    result=exporter.export_editor_project(project,fps=10)
    assert result['ok']
    import subprocess
    pixels=subprocess.check_output(['ffmpeg','-v','error','-i',result['output'],'-frames:v','1','-f','rawvideo','-pix_fmt','rgb24','-'])
    assert pixels[0]>200 and pixels[1]<30 and pixels[2]<30
    streams=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-of','json',result['output']]))['streams']
    assert not any(x['codec_type']=='audio' for x in streams)
