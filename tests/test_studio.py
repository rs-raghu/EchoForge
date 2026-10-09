from pathlib import Path
from unittest.mock import Mock
import pytest
from fastapi.testclient import TestClient
from echoforge import studio
from echoforge.core.storage import read_json
from echoforge.stages.renderer import render_jobs


@pytest.fixture
def client(isolated, monkeypatch):
    monkeypatch.setattr(studio,'PROJECTS_DIR',isolated/'projects')
    monkeypatch.setattr(studio,'APP_STATE_DIR',isolated/'data')
    return TestClient(studio.app)


def create(client):
    response=client.post('/api/projects',json={'title':'Fixture','artist':'Singer','sourceUrl':''})
    assert response.status_code == 200, response.text
    return response.json()


def test_create_dashboard_and_reload(client):
    p=create(client)
    assert client.get('/api/projects').json()[0]['id']==p['id']
    assert client.get('/api/dashboard').json()['queue'][0]['title']=='Fixture'
    assert client.get('/api/projects/'+p['id']).json()['sourceUrl']==''
    assert client.get('/api/logs').status_code==200


def test_drafts_approval_and_versions_survive_reopen(client):
    p=create(client); base='/api/projects/'+p['id']
    lines=[{'id':'line1','index':1,'type':'lyric','text':'Approved lyrics','timestamp':None}]
    assert client.put(base+'/lyrics?draft=true',json={'lines':lines}).json()['hasDraft']
    assert client.post(base+'/lyrics/approve',json={'lines':lines}).status_code==200
    assert client.get(base+'/lyrics').json()['lines']==lines
    assert Path(p['workspacePath'],'lyrics/lyrics.txt').read_text().strip()=='Approved lyrics'
    segments=[{'id':'s1','index':1,'start':0,'end':1,'text':'Approved lyrics','words':[]}]
    assert client.put(base+'/timestamps?draft=false',json={'segments':segments}).json()['hasDraft']
    result=client.post(base+'/timestamps/approve',json={'segments':segments})
    assert result.status_code==200, result.text
    assert result.json()['versions'][0]['isApproved'] is False
    assert result.json()['versions'][-1]['isApproved'] is True
    assert read_json(Path(p['workspacePath'])/'project_state.json')['stages']['verselock']=='done'
    changed=[{**lines[0],'text':'Changed lyric'}]
    assert client.post(base+'/lyrics/approve',json={'lines':changed}).status_code==200
    assert not client.get(base+'/render-readiness').json()['ready']


def test_invalid_timings_are_not_promoted(client):
    p=create(client); base='/api/projects/'+p['id']
    segments=[{'id':'s1','index':1,'start':2,'end':1,'text':'Oops','words':[]}]
    assert client.post(base+'/timestamps/validate',json={'segments':segments}).json()['warnings']
    assert client.post(base+'/timestamps/approve',json={'segments':segments}).status_code==422
    assert not Path(p['workspacePath'],'sync/final_synced_lyrics.json').exists()


def test_shift_moves_word_timings_and_rejects_negative(client):
    p=create(client); base='/api/projects/'+p['id']
    segments=[{'id':'s1','index':1,'start':1,'end':2,'text':'Word','words':[{'word':'Word','start':1,'end':2}]}]
    result=client.post(base+'/timestamps/shift',json={'segments':segments,'delta':.5,'segmentIds':['s1']})
    assert result.json()['segments'][0]['words'][0]['start']==1.5
    assert client.post(base+'/timestamps/shift',json={'segments':segments,'delta':-2,'segmentIds':[]}).status_code==422


def test_settings_and_templates_contract(client):
    assert client.get('/api/templates').json()[0]['settings']['animation']=='none'
    assert client.put('/api/settings',json={'defaultPrivacy':'unlisted','workspaceRoot':'SECRET'}).json()['defaultPrivacy']=='unlisted'
    assert client.get('/api/settings').json()['workspaceRoot']!='SECRET'


def test_upload_contract_requires_final_and_aware_schedule(client, monkeypatch):
    p=create(client); base='/api/projects/'+p['id']
    data={'projectId':p['id'],'title':'Approved title','description':'Approved description','tags':['a'],
          'privacy':'public','madeForKids':False,'playlist':'','thumbnailPath':'','scheduleTime':''}
    assert client.post(base+'/upload/approve',json=data).status_code==409
    assert client.put(base+'/upload/metadata',json={**data,'scheduleTime':'2099-01-01T00:00:00'}).status_code==422
    assert client.put(base+'/upload/metadata',json=data).json()['title']=='Approved title'
    file=Path(p['workspacePath'],'renders/final_video.mp4'); file.write_bytes(b'fixture')
    queued=Mock(return_value={'job_id':'000000000001','project_dir':p['workspacePath'],'status':'queued','options':{},'created_at':'fixture'})
    monkeypatch.setattr(render_jobs,'start_render_upload_job',queued)
    result=client.post(base+'/upload/approve',json=data)
    assert result.status_code==200, result.text
    assert queued.call_args.args[1]['title']=='Approved title'
    assert queued.call_args.args[1]['visibility']=='public'
    assert queued.call_args.args[1]['jobType']=='upload_youtube'


@pytest.mark.parametrize('path',['/api/settings','/api/projects','/api/dashboard'])
def test_cross_origin_and_rebinding_denied(client,path):
    assert client.get(path,headers={'Origin':'https://attacker.test'}).status_code==403
    assert client.get(path,headers={'Host':'attacker.test'}).status_code==403


def test_chart_options_reach_service(client,monkeypatch):
    from echoforge.stages.songscout import refresh
    fetch=Mock(return_value={'scraped':True,'inserted':3,'clean_songs':3})
    monkeypatch.setattr(refresh,'refresh_chart',fetch)
    assert client.post('/api/discovery/youtube-charts',json={'country':'IN','limit':10}).json()['added']==3
    assert fetch.call_args.kwargs['country']=='in'


def test_media_missing_and_unknown_are_explicit(client):
    p=create(client)
    assert client.get('/api/projects/'+p['id']+'/media/audio').status_code==404
    assert client.get('/api/projects/'+p['id']+'/media/secrets').status_code==404
