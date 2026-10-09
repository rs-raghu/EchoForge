import array
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
import pytest
from echoforge.core.security import validate_editor
from echoforge.core.storage import atomic_json, read_json

ROOT=Path(__file__).resolve().parents[1]


@pytest.fixture
def legacy():
    name='echoforge_legacy_test_backend'
    spec=importlib.util.spec_from_file_location(name,ROOT/'apps/webeditor_legacy/backend/main.py')
    module=importlib.util.module_from_spec(spec);sys.modules[name]=module;spec.loader.exec_module(module)
    return module


def test_legacy_mute_solo_produces_silent_audio(tmp_path, legacy):
    ffmpeg=shutil.which('ffmpeg')
    assert ffmpeg
    audio=tmp_path/'audio';audio.mkdir()
    subprocess.run([ffmpeg,'-y','-v','error','-f','lavfi','-i','sine=frequency=440:duration=0.5',str(audio/'source_audio.m4a')],check=True,timeout=30)
    project={'assets':{'audio':'audio/source_audio.m4a'},'tracks':[
        {'id':'lyrics','clips':[{'text':'Hi','start':0,'end':.5}]},
        {'id':'audio','muted':True,'clips':[{'id':'a1','src':'audio/source_audio.m4a','start':0,'end':.5,'volume':1}]}]}
    def peak():
        result=legacy.build_audio_timeline_file(tmp_path,project,tmp_path,ffmpeg,.5)
        raw=subprocess.run([ffmpeg,'-v','error','-i',str(result['path']),'-f','f32le','-'],capture_output=True,check=True,timeout=30).stdout
        values=array.array('f');values.frombytes(raw)
        return max(map(abs,values),default=0)
    assert peak()<.001
    project['tracks'][1]['muted']=False
    assert peak()>.01
    project['tracks'][0]['solo']=True
    assert peak()<.001
    assert legacy.normalized_lyric_clips(project,.5)
    project['tracks'][0]['solo']=False;project['tracks'][1]['solo']=True
    assert not legacy.normalized_lyric_clips(project,.5)


def test_legacy_state_writes_preserve_source_and_history(tmp_path, legacy):
    atomic_json(tmp_path/'project_state.json',{'youtube_url':'source','uploaded_youtube_url':'published','stages':{'tubeharbor':'done'}})
    legacy.write_project_state(tmp_path,{'title':'Edited','artist':'Singer','duration':1})
    state=read_json(tmp_path/'project_state.json')
    assert state['youtube_url']=='source'
    assert state['uploaded_youtube_url']=='published'
    assert state['stages']['tubeharbor']=='done'
    (tmp_path/'project_state.json').write_text('{bad')
    with pytest.raises(json.JSONDecodeError): legacy.read_json(tmp_path/'project_state.json')


@pytest.mark.parametrize('patch',[
    {'duration':1e12}, {'tracks':[{'clips':[{'start':0,'end':1,'style':{'strokeWidth':1e12}}]}]},
    {'tracks':[{'clips':[{'start':0,'end':1,'x':float('nan')}]}]},
])
def test_render_resource_bounds(tmp_path, patch):
    with pytest.raises(ValueError): validate_editor(patch,tmp_path)


def test_module_entry_renders_before_exit(tmp_path):
    from PIL import Image
    (tmp_path/'images').mkdir()
    Image.new('RGB',(320,240),'red').save(tmp_path/'images/red.png')
    atomic_json(tmp_path/'editor/editor_project.json',{'stage':'renderer_stage1_editor_project',
                'canvas':{'width':320,'height':240},'assets':{'background':'images/red.png'},
                'clips':[{'type':'text','start':0,'end':.2,'text':''}]})
    env=dict(os.environ);env['PYTHONPATH']=str(ROOT/'src')
    result=subprocess.run([sys.executable,'-m','echoforge.stages.renderer.exporter','--project',str(tmp_path),'--fps','10'],
                          cwd=tmp_path,env=env,capture_output=True,text=True,timeout=30)
    assert result.returncode==0,result.stderr
    assert read_json(tmp_path/'renders/render_report.json')['ok']
    assert (tmp_path/'renders/final_video.mp4').stat().st_size>0


@pytest.mark.skipif(os.name!='nt',reason='Windows batch launcher')
def test_launcher_uses_its_own_checkout(tmp_path):
    checkout=tmp_path/'copied checkout';checkout.mkdir()
    shutil.copy2(ROOT/'start_echoforge.bat',checkout/'start_echoforge.bat')
    (checkout/'run.bat').write_text('@echo off\necho FIXTURE_CWD=%CD%\necho FIXTURE_ARGS=%*\nexit /b 0\n')
    result=subprocess.run(['cmd.exe','/d','/c',str(checkout/'start_echoforge.bat')],cwd=tmp_path,
                          input='\n',capture_output=True,text=True,timeout=10)
    assert result.returncode==0,result.stderr
    assert f'FIXTURE_CWD={checkout}' in result.stdout
    assert 'FIXTURE_ARGS=all' in result.stdout
