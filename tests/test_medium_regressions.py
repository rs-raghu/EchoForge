import ast
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock
import pytest

from echoforge.core.storage import atomic_json, read_json, file_lock
from echoforge.core import sync_state
from echoforge.stages.songscout import database as db, cleaner, policy, refresh
from echoforge.stages.musevault import metadata_review, asset_collector
from echoforge.stages.verselock import lrc_parser, sync_runner, synced_reuse
from echoforge.stages.renderer import editor_project_v2, editor_project_builder
from echoforge.core.config import Settings
from tests.test_reliability import song


def test_current_chart_selection_preserves_history(isolated):
    old, current = song('Old', rank=1), song('Current', rank=2)
    db.upsert_songs([old], chart_snapshot=True)
    db.upsert_songs([current], chart_snapshot=True)
    assert db.get_next_available_song()['id'] == current['id']
    assert db.get_song(old['id'])['status'] == 'new'
    with pytest.raises(ValueError): db.upsert_songs([{}], chart_snapshot=True)
    assert db.get_next_available_song()['id'] == current['id']
    db.mark_song_status(current['id'], 'used')
    assert db.get_next_available_song() is None


def test_country_change_refreshes_in_same_cycle(isolated, monkeypatch):
    fetch = Mock(return_value=[{'lines':['1', 'Fixture', 'Singer']}])
    monkeypatch.setattr(refresh, 'scrape_youtube_charts', fetch)
    monkeypatch.setattr(refresh, 'delete_transient_debug_files', lambda: None)
    assert refresh.refresh_chart(country='in')['scraped']
    assert not refresh.refresh_chart(country='in')['scraped']
    assert refresh.refresh_chart()['scraped']
    assert '/global/' in fetch.call_args.kwargs['url']


@pytest.mark.parametrize('title', ['1985', '123', '1'])
def test_numeric_song_titles(title):
    parsed = cleaner.clean_row({'lines':['1',title,'Singer','2M views']})
    assert parsed['title'] == title and parsed['artist'] == 'Singer'


@pytest.mark.parametrize('text', ['Taxi', 'Oxygen', 'Xylophone'])
def test_search_keeps_x_inside_words(text):
    assert metadata_review.search_text(text) == text
    assert metadata_review.search_text('Artist x Singer') == 'Artist Singer'


def test_shared_lrc_offsets_multi_tags_and_blank_boundaries(tmp_path):
    path = tmp_path/'fixture.lrc'
    path.write_text('[offset:1000]\n[00:01.00][00:04.00]Hello\n[00:05.00]\n[00:07.00]Again\n[00:61.00]Invalid\n')
    raw = lrc_parser.parse_lrc_file(path)
    assert [(x.start_seconds,x.text) for x in raw] == [(2,'Hello'),(5,'Hello'),(6,''),(8,'Again')]
    stage1 = editor_project_builder.parse_lrc(path)
    v2 = editor_project_v2.parse_lrc(path)
    assert [(x.start,x.text) for x in stage1] == [(x['start'],x['text']) for x in v2]
    assert v2[1]['end'] == 6
    assert editor_project_v2.extract_lines_from_json({'lines':[x.to_dict() for x in raw]})[1]['end'] == 6
    assert editor_project_v2.normalize_line({'text':'bad','start':float('nan')}) is None


def test_invalid_lrc_falls_back_without_model_download(tmp_path, monkeypatch):
    (tmp_path/'lyrics').mkdir()
    (tmp_path/'lyrics/synced_lyrics.lrc').write_text('[00:01.00]\n')
    atomic_json(tmp_path/'project_state.json', {'stages':{}})
    fallback = Mock(return_value={'ok':False,'mode':'review_required'})
    monkeypatch.setattr(sync_runner, 'run_whisper_fallback_sync', fallback)
    assert not sync_runner.run_verselock_sync(tmp_path)['ok']
    assert fallback.call_count == 1
    assert fallback.call_args.kwargs['promote'] is False


def test_refresh_completion_uses_configured_calendar(isolated, monkeypatch):
    from zoneinfo import ZoneInfo
    instant = datetime(2026,10,8,20,0,tzinfo=timezone.utc).astimezone(ZoneInfo('Asia/Kolkata'))
    monkeypatch.setattr(policy, 'today_local', lambda: instant)
    db.record_scrape_result(success=True, clean_count=1)
    assert db.get_metadata('last_successful_scrape_date') == '2026-10-09'
    assert db.get_metadata('last_successful_scrape_window') == '2026-10-09'
    assert not policy.should_scrape_today().should_scrape


def test_fresh_settings_resolve_credential_aliases(tmp_path, monkeypatch):
    monkeypatch.delenv('YOUTUBE_TOKEN_PATH', raising=False)
    monkeypatch.setenv('YOUTUBE_TOKEN_FILE', str(tmp_path/'token.json'))
    monkeypatch.setenv('MAX_SONGS', '42')
    settings = Settings()
    assert settings.youtube_token_path == tmp_path/'token.json'
    assert settings.max_songs == 42
    monkeypatch.setenv('MAX_SONGS', 'bad')
    with pytest.raises(ValueError): Settings()


def test_concurrent_stage_updates_preserve_history(tmp_path):
    atomic_json(tmp_path/'project_state.json', {'source_youtube_url':'source','uploaded_youtube_url':'published','stages':{'tubeharbor':'done'}})
    with ThreadPoolExecutor(8) as pool:
        list(pool.map(lambda n:asset_collector.update_project_state(tmp_path,str(n),'done'),range(30)))
    state = read_json(tmp_path/'project_state.json')
    assert len(state['stages']) == 31
    assert state['uploaded_youtube_url'] == 'published'
    (tmp_path/'project_state.json').write_text('{bad')
    with pytest.raises(json.JSONDecodeError): synced_reuse.update_project_state(tmp_path,{'ok':True})
    assert (tmp_path/'project_state.json').read_text() == '{bad'


def test_interrupted_timing_publication_rejects_mixed_pair(tmp_path, monkeypatch):
    sync_state.publish_sync(tmp_path,'[00:00.00]Old\n',{'lines':[{'start':0,'text':'Old'}]})
    original = sync_state.atomic_json
    def interrupted(path, payload):
        if path.name == 'final_synced_lyrics.json': raise OSError('Interrupted fixture')
        return original(path,payload)
    monkeypatch.setattr(sync_state, 'atomic_json', interrupted)
    with pytest.raises(OSError): sync_state.publish_sync(tmp_path,'[00:00.00]New\n',{'lines':[]})
    with pytest.raises(ValueError,match='interrupted'): editor_project_v2.load_final_lines(tmp_path)
    monkeypatch.setattr(sync_state, 'atomic_json', original)
    sync_state.publish_sync(tmp_path,'[00:00.00]New\n',{'lines':[{'start':0,'text':'New'}]})
    assert editor_project_v2.load_final_lines(tmp_path)[0]['text'] == 'New'
    (tmp_path/'sync/final_synced_lyrics.lrc').write_text('changed')
    with pytest.raises(ValueError,match='outside'): sync_state.validate_sync_pair(tmp_path)


def test_atomic_failure_preserves_existing_json(tmp_path, monkeypatch):
    from echoforge.core import storage
    path=tmp_path/'state.json'; atomic_json(path,{'old':True})
    monkeypatch.setattr(storage.os, 'replace', Mock(side_effect=PermissionError('fixture')))
    with pytest.raises(PermissionError): atomic_json(path,{'new':True})
    assert read_json(path) == {'old':True}
    assert not list(tmp_path.glob('*.tmp'))


def test_lock_is_reentrant(tmp_path):
    with file_lock(tmp_path/'lock',timeout=.1):
        with file_lock(tmp_path/'lock',timeout=.1): pass


def test_failed_upload_report_is_not_success(tmp_path):
    import project_status
    atomic_json(tmp_path/'project_state.json',{'stages':{'tubeharbor':'done'}})
    atomic_json(tmp_path/'upload/youtube_upload_report.json',{'ok':False,'video_id':'invalid','url':'invalid'})
    result=project_status.status(tmp_path)
    assert not result['stages']['uploaded']
    assert result['youtube_url'] == ''


def test_declared_python_310_syntax():
    root=Path(__file__).resolve().parents[1]
    for folder in ['src','scripts']:
        for path in (root/folder).rglob('*.py'):
            ast.parse(path.read_text(encoding='utf-8'),filename=str(path),feature_version=(3,10))

