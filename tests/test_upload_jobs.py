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


def test_saved_settings_and_explicit_false_empty_values_reach_youtube(remote):
    project,video,yt,request=remote
    atomic_json(project/'upload/youtube_metadata.json',{'metadata':{
        'title':'Saved title','description':'Saved description','tags':['saved'],
        'categoryId':'22','madeForKids':True,'privacy':'public'}})
    result=uploader.upload_to_youtube(video,project,{'metadata':{
        'title':'Edited title','description':'','tags':[], 'category_id':'24','made_for_kids':False}})
    assert result['ok']
    assert yt.videos.return_value.insert.call_args.kwargs['body']=={
        'snippet':{'title':'Edited title','description':'','tags':[],'categoryId':'24'},
        'status':{'privacyStatus':'public','selfDeclaredMadeForKids':False}}


def test_nested_schedule_and_visibility_reach_youtube(remote):
    project,video,yt,request=remote
    result=uploader.upload_to_youtube(video,project,{'metadata':{
        'title':'Scheduled title','privacy':'public','scheduleTime':'2099-01-01T12:00:00+05:30'}})
    assert result['ok']
    assert result['metadata']['status']=={'privacyStatus':'private',
        'selfDeclaredMadeForKids':False,'publishAt':'2099-01-01T06:30:00+00:00'}
    assert uploader.upload_to_youtube(video,project,{})['reused_existing_upload']


def test_historical_upload_without_video_fingerprint_requires_review(remote):
    project,video,yt,request=remote
    atomic_json(project/'upload/youtube_upload_report.json',{'ok':True,'video_id':'old123','url':'OLD'})
    result=uploader.upload_to_youtube(video,project,{})
    assert not result['ok'] and 'no video fingerprint' in result['reason']
    yt.videos.return_value.insert.assert_not_called()


def test_render_without_metadata_does_not_create_blank_upload_defaults(isolated,monkeypatch):
    monkeypatch.setattr(render_jobs,'export_editor_project',Mock(return_value={'ok':True,'output':'fixture.mp4'}))
    assert render_jobs.start_render_upload_job(isolated,{},background=False)['ok']
    assert not (isolated/'upload/youtube_metadata.json').exists()


@pytest.mark.parametrize('change',['title','video','thumbnail'])
def test_changed_published_project_does_not_silently_reuse_old_upload(remote,change):
    project,video,yt,request=remote
    assert uploader.upload_to_youtube(video,project,{'title':'First approved title'})['ok']
    options={}
    if change=='title': options={'metadata':{'title':'Changed title'}}
    if change=='video': video.write_bytes(b'NEW EDITED VIDEO')
    if change=='thumbnail':
        selected=project/'images/changed.png'; selected.parent.mkdir(); selected.write_bytes(b'NEW THUMB')
        options={'thumbnailPath':'images/changed.png'}
    result=uploader.upload_to_youtube(video,project,options)
    assert not result['ok']
    assert result['existing_video_id']=='remote123'
    assert 'changes were not applied' in result['reason']
    assert result['video_changed']==(change=='video')
    assert yt.videos.return_value.insert.call_count==1
    assert upload_db.get_upload(project)['ok']


@pytest.mark.parametrize('visibility',['public','schedule'])
def test_actual_render_upload_dialog_settings_survive_reopen_and_reach_youtube(remote,monkeypatch,visibility):
    """Real browser -> HTTP handler -> job -> uploader; only render/Google mocked."""
    import threading
    from http.server import ThreadingHTTPServer
    from playwright.sync_api import sync_playwright
    from echoforge.stages.renderer import server
    from echoforge.core.storage import read_json
    project,video,yt,request=remote
    atomic_json(project/'editor/editor_project.json',{'schema':'echoforge.webeditor.v2',
        'project':{'title':'Fixture','artist':'Singer','duration':1},'canvas':{'width':320,'height':240},
        'assets':{},'tracks':[{'id':'lyrics','type':'text','clips':[
            {'id':'l1','type':'text','text':'Hello','start':0,'end':1,'x':160,'y':120}]}]})
    atomic_json(project/'upload/youtube_metadata.json',{'metadata':{
        'title':'Previously saved title','description':'Old description','tags':['old'],
        'categoryId':'22','madeForKids':True,'visibility':'unlisted'}})
    monkeypatch.setattr(server,'PROJECT_DIR',project,raising=False)
    monkeypatch.setattr(render_jobs,'export_editor_project',Mock(return_value={'ok':True,'output':str(video)}))
    http=ThreadingHTTPServer(('127.0.0.1',0),server.Handler)
    thread=threading.Thread(target=http.serve_forever); thread.start()
    try:
        with sync_playwright() as pw:
            browser=pw.chromium.launch(headless=True); page=browser.new_page(timezone_id='Asia/Kolkata')
            page.goto('http://127.0.0.1:'+str(http.server_port))
            page.wait_for_function('typeof window.saveProject === "function"')
            page.locator('#efRenderUploadBtn').click()
            field=page.locator('.efru-modal [data-title]')
            page.wait_for_function('document.querySelector(".efru-modal [data-title]").disabled === false')
            assert field.input_value()=='Previously saved title'
            assert page.locator('[data-visibility]').input_value()=='unlisted'
            assert page.locator('[data-kids]').input_value()=='true'
            field.fill('Edited approved title')
            page.locator('[data-description]').fill('Edited description')
            page.locator('[data-tags]').fill('custom, reviewed')
            page.locator('[data-category]').fill('24')
            page.locator('[data-kids]').select_option('false')
            page.locator('[data-visibility]').select_option(visibility)
            if visibility=='schedule': page.locator('[data-schedule]').fill('2099-01-01T12:00')
            page.locator('[data-render-upload]').click()
            page.wait_for_function('document.querySelector("[data-status]").textContent.includes("YouTube: https://www.youtube.com/watch?v=remote123")')
            body=yt.videos.return_value.insert.call_args.kwargs['body']
            expected_status={'privacyStatus':'public','selfDeclaredMadeForKids':False}
            if visibility=='schedule': expected_status.update(privacyStatus='private',publishAt='2099-01-01T06:30:00+00:00')
            assert body=={'snippet':{'title':'Edited approved title','description':'Edited description',
                'tags':['custom','reviewed'],'categoryId':'24'},
                'status':expected_status}
            assert read_json(project/'upload/youtube_metadata.json')['metadata']['title']=='Edited approved title'
            page.locator('[data-close]').click()
            page.locator('#efRenderUploadBtn').click()
            page.wait_for_function('document.querySelector(".efru-modal [data-title]").disabled === false')
            assert field.input_value()=='Edited approved title'
            assert page.locator('[data-visibility]').input_value()==visibility
            if visibility=='schedule': assert page.locator('[data-schedule]').input_value()=='2099-01-01T12:00'
            assert page.locator('[data-category]').input_value()=='24'
            assert page.locator('[data-kids]').input_value()=='false'
            field.fill('Edit after publication')
            page.locator('[data-render-upload]').click()
            page.wait_for_function('document.querySelector("[data-status]").textContent.includes("changes were not applied")')
            assert yt.videos.return_value.insert.call_count==1
            browser.close()
    finally:
        http.shutdown(); thread.join(); http.server_close()
