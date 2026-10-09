from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import subprocess
from unittest.mock import Mock
import pytest

from echoforge.core.storage import atomic_json, read_json
from echoforge.core import project_builder
from echoforge.stages.songscout import database as db, policy, refresh, cleaner
from echoforge.stages.musevault.audio_normalizer import normalize_project_audio
from echoforge.stages.verselock.synced_reuse import reuse_existing_synced_lyrics
from echoforge.stages.verselock.timestamp_transfer import timestamp_transfer_sync
from echoforge.stages.renderer import exporter, render_jobs
from echoforge.stages.tubeharbor import youtube_uploader as uploader, upload_db


def song(title="Fixture", artist="Singer", rank=1):
    return {"id": cleaner.unique_song_id(title, artist), "title":title, "artist":artist, "rank":rank}


@pytest.mark.parametrize("day,completed,expected", [
    ("2026-10-09", None, True), ("2026-10-10", None, True),
    ("2026-10-11", "2026-10-09", False), ("2026-10-16", "2026-10-09", True),
    ("2026-10-08", "2026-10-02", False), ("2026-10-09", "2026-10-02", True)])
def test_weekly_cycles(isolated, monkeypatch, day, completed, expected):
    monkeypatch.setattr(policy, "today_local", lambda:datetime.fromisoformat(day))
    if completed: db.set_metadata("last_successful_scrape_window", completed)
    assert policy.should_scrape_today().should_scrape is expected


def test_empty_refresh_is_retryable(isolated, monkeypatch):
    monkeypatch.setattr(refresh, "scrape_youtube_charts", lambda **kw:[])
    with pytest.raises(ValueError): refresh.refresh_chart()
    assert policy.should_scrape_today().should_scrape
    assert db.get_metadata("last_scrape_status") == "failed"


def test_parallel_refresh_once(isolated, monkeypatch):
    fetch=Mock(return_value=[{"lines":["1", "Fixture", "Singer"]}])
    monkeypatch.setattr(refresh, "scrape_youtube_charts", fetch)
    monkeypatch.setattr(refresh, "delete_transient_debug_files", lambda:None)
    with ThreadPoolExecutor(2) as pool:
        results=list(pool.map(lambda _:refresh.refresh_chart(), range(2)))
    assert fetch.call_count == 1
    assert sum(r["scraped"] for r in results) == 1


def test_unicode_identity_and_normalization():
    assert cleaner.unique_song_id("नमस्ते", "कलाकार") != cleaner.unique_song_id("संगीत", "कलाकार")
    assert cleaner.unique_song_id("Café", "Singer") == cleaner.unique_song_id("Cafe\u0301", "Singer")


def test_parallel_allocation_and_reopen_preserves_used(isolated):
    a,b=song(),song("Second")
    db.upsert_songs([a,b])
    with ThreadPoolExecutor(2) as pool:
        results=list(pool.map(lambda _:project_builder.init_next_project(), range(2)))
    assert len({r['project_dir'] for r in results}) == 2
    assert len({r['song']['id'] for r in results}) == 2
    db.mark_song_status(a['id'], 'used')
    project_builder.init_project_by_song_id(a['id'])
    assert db.get_song(a['id'])['status'] == 'used'


def test_connection_context_closes(isolated):
    with db.connect() as conn: conn.execute('SELECT 1')
    with pytest.raises(Exception, match='closed'): conn.execute('SELECT 1')


def test_zero_byte_audio_not_success(tmp_path):
    (tmp_path/'audio').mkdir()
    (tmp_path/'audio/source_audio.m4a').touch()
    assert not normalize_project_audio(tmp_path)['ok']


def test_force_audio_atomic_conversion(tmp_path):
    (tmp_path/'audio').mkdir()
    source=tmp_path/'audio/source_audio.m4a'
    subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','sine=frequency=440:duration=0.2','-c:a','aac',str(source)],check=True)
    assert normalize_project_audio(tmp_path,force=True)['ok']
    assert not list((tmp_path/'audio').glob('.normalization-*.m4a'))


def test_sync_rebuilds_changed_and_corrupt_outputs(tmp_path):
    (tmp_path/'lyrics').mkdir()
    src=tmp_path/'lyrics/synced_lyrics.lrc'
    src.write_text('[00:01.00]Old line\n')
    assert reuse_existing_synced_lyrics(tmp_path)['ok']
    src.write_text('[00:02.00]New line\n')
    (tmp_path/'sync/final_synced_lyrics.json').write_text('{bad')
    assert reuse_existing_synced_lyrics(tmp_path)['ok']
    assert read_json(tmp_path/'sync/final_synced_lyrics.json')['lines'][0]['text'] == 'New line'


def test_failed_transfer_preserves_approved_final(tmp_path):
    (tmp_path/'lyrics').mkdir(); (tmp_path/'sync').mkdir()
    (tmp_path/'lyrics/lyrics.txt').write_text('One\nTwo\nThree\n')
    atomic_json(tmp_path/'sync/whisper_advanced_transcript.json', {'segments':[{'start':1,'end':2,'text':'One'}], 'words':[]})
    approved=tmp_path/'sync/final_synced_lyrics.lrc'; approved.write_text('APPROVED')
    result=timestamp_transfer_sync(tmp_path,promote=True)
    assert not result['ok'] and not result['promoted_to_final']
    assert approved.read_text() == 'APPROVED'


def test_render_contracts(tmp_path):
    assert exporter.pos(50,1920,960) == 50
    assert exporter.build_audio(tmp_path,[],1,tmp_path) is None
    stage1={'stage':'renderer_stage1_editor_project','assets':{'background':'images/background.png','audio':'audio/source_audio.m4a'},'clips':[{'type':'text','start':0,'end':1,'text':'Hi'}]}
    assert {exporter.clip_type(c) for c in exporter.clips_from(stage1)} == {'background','audio','lyric'}
    assert exporter.clips_from({'schema':'echoforge.webeditor.v2','assets':stage1['assets'],'tracks':[]}) == []


def test_missing_audio_rejected(tmp_path):
    with pytest.raises(FileNotFoundError):
        exporter.build_audio(tmp_path,[{'type':'audio','start':1,'end':2,'asset':'audio/missing.m4a'}],2,tmp_path)


def test_dead_worker_recovers(isolated):
    atomic_json(render_jobs._JOBS_FILE, {'old':{'status':'running','project_dir':str(isolated),'job_id':'old'}})
    assert render_jobs.get_job_status('old')['status'] == 'interrupted'


@pytest.mark.parametrize('schedule', ['2020-01-01T00:00:00Z','2099-01-01T00:00:00','bad'])
def test_unsafe_schedules_rejected(schedule):
    with pytest.raises(ValueError): uploader.privacy({'visibility':'schedule','scheduleAt':schedule})


def test_schedule_normalized_and_private():
    assert uploader.privacy({'visibility':'schedule','scheduleAt':'2099-01-01T12:00:00+05:30'}) == ('private','2099-01-01T06:30:00+00:00')


def test_corrupt_upload_ledger_fails_closed(isolated):
    upload_db.DB_PATH.write_text('{invalid')
    with pytest.raises(ValueError): upload_db.is_uploaded(isolated)


def test_known_upload_prevents_network_and_preserves_source(isolated, monkeypatch):
    project=isolated/'projects/0001_fixture'; project.mkdir(parents=True)
    atomic_json(project/'project_state.json', {'youtube_url':'SOURCE','song_id':None,'stages':{'musevault':'done'}})
    atomic_json(project/'upload/youtube_upload_report.json', {'ok':True,'video_id':'remote123','url':'OUTPUT'})
    remote=Mock(); monkeypatch.setattr(uploader,'service',remote)
    assert uploader.upload_to_youtube(project/'renders/missing.mp4',project,{})['reused_existing_upload']
    remote.assert_not_called()
    state=read_json(project/'project_state.json')
    assert state['youtube_url'] == 'SOURCE' and state['uploaded_youtube_url'] == 'OUTPUT'
    assert state['stages']['tubeharbor'] == 'done'


def test_uncertain_upload_does_not_retry(isolated, monkeypatch):
    upload_db.record_upload(isolated, {'ok':False,'status':'uncertain'})
    remote=Mock(); monkeypatch.setattr(uploader,'service',remote)
    assert uploader.upload_to_youtube(isolated/'video.mp4',isolated,{})['requires_reconciliation']
    remote.assert_not_called()
