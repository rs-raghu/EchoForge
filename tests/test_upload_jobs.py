import sys
from types import SimpleNamespace
from threading import Event
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock
import pytest
from echoforge.core.storage import atomic_json
from echoforge.stages.tubeharbor import youtube_uploader as uploader, upload_db
from echoforge.stages.renderer import render_jobs


@pytest.fixture
def remote(isolated,monkeypatch):
    project=isolated/'projects/fixture'; project.mkdir(parents=True)
    video=project/'renders/final_video.mp4'; video.parent.mkdir(); video.write_bytes(b'MOCK VIDEO')
    atomic_json(project/'project_state.json',{'title':'Song','artist':'Singer','youtube_url':'SOURCE','stages':{}})
    monkeypatch.setitem(sys.modules,'googleapiclient.http',SimpleNamespace(MediaFileUpload=lambda *a,**kw:SimpleNamespace()))
    yt=Mock(); request=Mock(); request.next_chunk.return_value=(None,{'id':'remote123'})
    yt.videos.return_value.insert.return_value=request
    service=Mock(return_value=(yt,None)); monkeypatch.setattr(uploader,'service',service)
    return project,video,yt,request


def test_parallel_upload_inserts_once_with_approved_metadata(remote):
    project,video,yt,request=remote
    options={'visibility':'public','metadata':{'title':'Approved custom title','description':'Approved description','tags':['one','two'],'made_for_kids':True}}
    with ThreadPoolExecutor(2) as pool:
        results=list(pool.map(lambda _:uploader.upload_to_youtube(video,project,options),range(2)))
    assert all(r['ok'] for r in results)
    assert yt.videos.return_value.insert.call_count==1
    body=yt.videos.return_value.insert.call_args.kwargs['body']
    assert body['snippet']['title']=='Approved custom title'
    assert body['status']=={'privacyStatus':'public','selfDeclaredMadeForKids':True}
    assert upload_db.get_upload(project)['video_id']=='remote123'


@pytest.mark.parametrize('response',[{}, {'id':''}, {'error':'bad'}])
def test_missing_remote_id_remains_uncertain(remote,response):
    project,video,yt,request=remote; request.next_chunk.return_value=(None,response)
    assert not uploader.upload_to_youtube(video,project,{})['ok']
    assert uploader.upload_to_youtube(video,project,{})['requires_reconciliation']
    assert yt.videos.return_value.insert.call_count==1
    assert upload_db.get_upload(project)['status']=='uncertain'


def test_network_disconnect_and_thumbnail_failure_do_not_duplicate(remote):
    project,video,yt,request=remote; request.next_chunk.side_effect=ConnectionError('Disconnected after insert')
    assert uploader.upload_to_youtube(video,project,{})['requires_reconciliation']
    assert uploader.upload_to_youtube(video,project,{})['requires_reconciliation']
    assert yt.videos.return_value.insert.call_count==1


def test_thumbnail_failure_preserves_remote_success(remote):
    project,video,yt,request=remote
    thumb=project/'renders/upload_thumbnail.jpg'; thumb.write_bytes(b'MOCK THUMB')
    yt.thumbnails.return_value.set.return_value.execute.side_effect=RuntimeError('Thumbnail unavailable')
    first=uploader.upload_to_youtube(video,project,{})
    assert first['ok'] and not first['thumbnail_uploaded']
    assert uploader.upload_to_youtube(video,project,{})['reused_existing_upload']
    assert yt.videos.return_value.insert.call_count==1


def test_approved_thumbnail_path_reaches_upload(remote, monkeypatch):
    project,video,yt,request=remote
    selected=project/'images/approved.png';selected.parent.mkdir();selected.write_bytes(b'MOCK THUMB')
    monkeypatch.setitem(sys.modules,'googleapiclient.http',SimpleNamespace(MediaFileUpload=lambda path,**kw:SimpleNamespace(filename=str(path))))
    assert uploader.upload_to_youtube(video,project,{'thumbnailPath':'images/approved.png'})['ok']
    assert yt.thumbnails.return_value.set.call_args.kwargs['media_body'].filename==str(selected)


@pytest.mark.parametrize('options',[{'thumbnailPath':'../.secrets/token.json'},{'madeForKids':'false'}])
def test_invalid_approved_metadata_rejected_before_insert(remote,options):
    project,video,yt,request=remote
    with pytest.raises(ValueError): uploader.upload_to_youtube(video,project,options)
    yt.videos.return_value.insert.assert_not_called()
    assert not upload_db.get_upload(project)


def test_upload_http_transport_has_timeout(tmp_path,monkeypatch):
    from google.oauth2.credentials import Credentials
    from googleapiclient import discovery
    client=tmp_path/'client.json';client.write_text('FIXTURE')
    token=tmp_path/'token.json';token.write_text('FIXTURE')
    monkeypatch.setattr(uploader,'cred_paths',lambda project:(client,token))
    monkeypatch.setattr(Credentials,'from_authorized_user_file',Mock(return_value=Mock(valid=True)))
    build=Mock();monkeypatch.setattr(discovery,'build',build)
    service,error=uploader.service(tmp_path)
    assert error is None
    assert build.call_args.kwargs['http'].http.timeout==60
    assert build.call_args.kwargs['cache_discovery'] is False


def test_render_failure_never_uploads_stale_file(isolated,monkeypatch):
    render=Mock(return_value={'ok':False,'reason':'Render rejected'})
    upload=Mock(); monkeypatch.setattr(render_jobs,'export_editor_project',render); monkeypatch.setattr(render_jobs,'upload_to_youtube',upload)
    job=render_jobs.start_render_upload_job(isolated,{'upload':True},background=False)
    assert job['status']=='failed'
    upload.assert_not_called()


def test_job_guard_uses_persisted_registry(isolated,monkeypatch):
    entered=Event(); release=Event()
    def render(*args):
        entered.set(); assert release.wait(5)
        return {'ok':True,'output':'fixture.mp4'}
    monkeypatch.setattr(render_jobs,'export_editor_project',render)
    with ThreadPoolExecutor(2) as pool:
        first=pool.submit(render_jobs.start_render_upload_job,isolated,{},background=False)
        assert entered.wait(5)
        second=render_jobs.start_render_upload_job(isolated,{})
        assert second['already_running']
        release.set(); first_result=first.result()
    assert first_result['job_id']==second['job_id']
    assert first_result['status']=='completed'


def test_request_json_contract(isolated,monkeypatch):
    import render_upload_project
    req=isolated/'request.json'
    body={'upload':True,'visibility':'public','metadata':{'title':'Approved'}}
    atomic_json(req,body)
    execute=Mock(return_value={'ok':True,'status':'completed'})
    monkeypatch.setattr(render_upload_project,'start_render_upload_job',execute)
    monkeypatch.setattr(sys,'argv',['render_upload_project.py','--project',str(isolated),'--request',str(req)])
    assert render_upload_project.main()==0
    assert execute.call_args.args[1]==body
