import sys
from types import SimpleNamespace
from unittest.mock import Mock
from echoforge.stages.verselock import whisper_advanced as whisper


def test_whisper_cache_uses_inputs_options_and_complete_outputs(tmp_path,monkeypatch):
    folder=tmp_path/'audio'; folder.mkdir()
    audio=folder/'source_audio.m4a'; audio.write_bytes(b'Fixture audio A')
    words=[SimpleNamespace(start=i*.1,end=i*.1+.09,word=f'word{i}',probability=.9) for i in range(8)]
    segment=SimpleNamespace(start=0,end=1,text='Fixture words',words=words)
    model=Mock(); model.transcribe.side_effect=lambda *a,**kw:([segment],SimpleNamespace(language='en',duration=1))
    constructor=Mock(return_value=model)
    monkeypatch.setitem(sys.modules,'faster_whisper',SimpleNamespace(WhisperModel=constructor))
    monkeypatch.setattr(whisper,'_prepare_cpu_audio',lambda *a,**kw:audio)
    assert whisper.run_advanced_whisper_probe(tmp_path)['ok']
    assert whisper.run_advanced_whisper_probe(tmp_path)['ok']
    assert constructor.call_count==1
    audio.write_bytes(b'Fixture audio B')
    assert whisper.run_advanced_whisper_probe(tmp_path)['ok']
    assert constructor.call_count==2
    assert whisper.run_advanced_whisper_probe(tmp_path,model_size='small')['ok']
    assert constructor.call_count==3
    (tmp_path/'sync/whisper_word_rough_lrc.lrc').write_text('CORRUPT')
    assert whisper.run_advanced_whisper_probe(tmp_path,model_size='small')['ok']
    assert constructor.call_count==4


def test_sparse_cache_never_becomes_success(tmp_path,monkeypatch):
    (tmp_path/'audio').mkdir(); audio=tmp_path/'audio/source_audio.m4a'; audio.write_bytes(b'Fixture')
    segment=SimpleNamespace(start=0,end=1,text='Sparse',words=[SimpleNamespace(start=0,end=1,word='Sparse',probability=.9)])
    model=Mock(); model.transcribe.side_effect=lambda *a,**kw:([segment],SimpleNamespace(language='en',duration=1))
    monkeypatch.setitem(sys.modules,'faster_whisper',SimpleNamespace(WhisperModel=Mock(return_value=model)))
    monkeypatch.setattr(whisper,'_prepare_cpu_audio',lambda *a,**kw:audio)
    assert not whisper.run_advanced_whisper_probe(tmp_path)['ok']
    assert not whisper.run_advanced_whisper_probe(tmp_path)['ok']
