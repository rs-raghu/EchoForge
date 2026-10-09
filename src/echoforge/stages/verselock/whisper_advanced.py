from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from dataclasses import asdict, dataclass
from echoforge.core.media import fingerprint, audio_duration
from echoforge.core.storage import atomic_json
from pathlib import Path
from typing import Any


AUDIO_EXTS = [
    'source_audio.m4a',
    'source_audio.mp3',
    'source_audio.wav',
    'source_audio.webm',
    'source_audio.mp4',
]


@dataclass
class WhisperAdvancedResult:
    ok: bool
    mode: str
    reason: str | None
    engine: str
    model_size: str
    compute_type: str
    language: str | None
    audio: str | None
    prepared_audio: str | None
    output_json: str | None
    output_word_lrc: str | None
    output_segment_lrc: str | None
    report_path: str | None
    segment_count: int
    word_count: int
    line_count: int
    duration: float | None
    project_dir: str
    note: str


def _json_dump(path: Path, data: Any) -> None:
    atomic_json(path, data)


def _format_ts(seconds: float) -> str:
    seconds = max(float(seconds), 0.0)
    minutes = int(seconds // 60)
    rem = seconds - minutes * 60
    return f'[{minutes:02d}:{rem:05.2f}]'


def _find_audio(project_dir: Path) -> Path | None:
    audio_dir = project_dir / 'audio'
    for name in AUDIO_EXTS:
        candidate = audio_dir / name
        if candidate.exists():
            return candidate
    for candidate in sorted(audio_dir.glob('source_audio.*')):
        if candidate.is_file():
            return candidate
    return None


def _ffmpeg_exists() -> bool:
    return shutil.which('ffmpeg') is not None


def _prepare_cpu_audio(project_dir: Path, audio_path: Path, force: bool) -> Path:
    """Create 16kHz mono WAV for more stable CPU ASR."""
    out = project_dir / 'sync' / 'whisper_input_16k_mono.wav'
    signature = out.with_suffix('.source.json')
    try:
        cached = json.loads(signature.read_text())
    except (OSError, ValueError):
        cached = {}
    if not force and cached.get('sha256') == fingerprint(audio_path) and audio_duration(out):
        return out
    if not _ffmpeg_exists():
        return audio_path
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        'ffmpeg', '-y',
        '-i', str(audio_path),
        '-vn',
        '-ac', '1',
        '-ar', '16000',
        '-af', 'loudnorm=I=-16:TP=-1.5:LRA=11',
        str(out),
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    atomic_json(signature, {'sha256': fingerprint(audio_path)})
    return out


def _words_from_segments(segments: list[dict]) -> list[dict]:
    words: list[dict] = []
    for seg in segments:
        for word in seg.get('words') or []:
            text = (word.get('word') or '').strip()
            if not text:
                continue
            words.append({
                'start': float(word.get('start') or seg.get('start') or 0.0),
                'end': float(word.get('end') or seg.get('end') or 0.0),
                'word': text,
                'probability': word.get('probability'),
            })
    return words


def _write_segment_lrc(path: Path, segments: list[dict]) -> int:
    lines = []
    for seg in segments:
        text = ' '.join((seg.get('text') or '').split()).strip()
        if not text:
            continue
        lines.append(f"{_format_ts(float(seg.get('start') or 0.0))}{text}")
    path.write_text('\n'.join(lines) + ('\n' if lines else ''), encoding='utf-8')
    return len(lines)


def _write_word_grouped_lrc(path: Path, words: list[dict]) -> int:
    """Group word timestamps into readable lyric-like lines.

    This is not final lyric alignment. It turns Whisper word timestamps into useful rough LRC lines.
    """
    if not words:
        path.write_text('', encoding='utf-8')
        return 0

    lines = []
    current = []
    start = words[0]['start']
    last_end = words[0]['end']

    def flush() -> None:
        nonlocal current, start, last_end
        if not current:
            return
        text = ' '.join(w['word'] for w in current).replace(' ,', ',').replace(' .', '.').replace(' !', '!').replace(' ?', '?')
        lines.append(f'{_format_ts(start)}{text}')
        current = []

    for word in words:
        w = word['word']
        gap = float(word['start']) - float(last_end)
        duration = float(word['end']) - float(start)
        punctuation_break = w.endswith(('.', ',', '?', '!', ';', ':'))
        too_many_words = len(current) >= 7
        too_long = duration >= 4.2
        big_gap = gap >= 0.85

        if current and (too_many_words or too_long or big_gap):
            flush()
            start = float(word['start'])

        current.append(word)
        last_end = float(word['end'])

        if punctuation_break and len(current) >= 3:
            flush()
            if words.index(word) + 1 < len(words):
                start = float(word['end'])

    flush()
    path.write_text('\n'.join(lines) + ('\n' if lines else ''), encoding='utf-8')
    return len(lines)


def run_advanced_whisper_probe(
    project: str | Path,
    model_size: str = 'medium',
    compute_type: str = 'int8',
    language: str | None = None,
    force: bool = False,
    beam_size: int = 5,
    vad_filter: bool = False,
) -> dict:
    project_dir = Path(project)
    sync_dir = project_dir / 'sync'
    sync_dir.mkdir(parents=True, exist_ok=True)

    audio_path = _find_audio(project_dir)
    if not audio_path:
        result = WhisperAdvancedResult(
            ok=False,
            mode='whisper_advanced_probe',
            reason='No audio file found in project/audio.',
            engine='faster-whisper',
            model_size=model_size,
            compute_type=compute_type,
            language=language,
            audio=None,
            prepared_audio=None,
            output_json=None,
            output_word_lrc=None,
            output_segment_lrc=None,
            report_path=None,
            segment_count=0,
            word_count=0,
            line_count=0,
            duration=None,
            project_dir=str(project_dir),
            note='Audio is required before Whisper can run.',
        )
        return asdict(result)

    output_json = sync_dir / 'whisper_advanced_transcript.json'
    output_word_lrc = sync_dir / 'whisper_word_rough_lrc.lrc'
    output_segment_lrc = sync_dir / 'whisper_segment_rough_lrc.lrc'
    report_path = sync_dir / 'whisper_advanced_report.json'

    signature = {'audio_sha256': fingerprint(audio_path), 'model_size': model_size,
                 'compute_type': compute_type, 'requested_language': language,
                 'beam_size': beam_size, 'vad_filter': vad_filter}
    try:
        data = json.loads(output_json.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        data = {}
    valid_cache = (all(data.get(k) == v for k, v in signature.items())
                   and len(data.get('words') or []) >= 8
                   and output_word_lrc.is_file() and output_segment_lrc.is_file()
                   and bool(output_word_lrc.read_text(encoding='utf-8').strip())
                   and data.get('word_lrc_sha256') == fingerprint(output_word_lrc)
                   and data.get('segment_lrc_sha256') == fingerprint(output_segment_lrc))
    if valid_cache and not force:
        result = WhisperAdvancedResult(
            ok=True,
            mode='whisper_advanced_probe',
            reason=None,
            engine='faster-whisper',
            model_size=model_size,
            compute_type=compute_type,
            language=data.get('language'),
            audio=str(audio_path),
            prepared_audio=data.get('prepared_audio'),
            output_json=str(output_json),
            output_word_lrc=str(output_word_lrc),
            output_segment_lrc=str(output_segment_lrc),
            report_path=str(report_path),
            segment_count=len(data.get('segments') or []),
            word_count=len(data.get('words') or []),
            line_count=len(output_word_lrc.read_text(encoding='utf-8').splitlines()),
            duration=data.get('duration'),
            project_dir=str(project_dir),
            note='Reused existing advanced Whisper outputs.',
        )
        return asdict(result)

    try:
        from faster_whisper import WhisperModel
    except Exception as exc:  # noqa: BLE001
        result = WhisperAdvancedResult(
            ok=False,
            mode='whisper_advanced_probe',
            reason=f'faster-whisper is not installed or failed to import: {exc}',
            engine='faster-whisper',
            model_size=model_size,
            compute_type=compute_type,
            language=language,
            audio=str(audio_path),
            prepared_audio=None,
            output_json=None,
            output_word_lrc=None,
            output_segment_lrc=None,
            report_path=None,
            segment_count=0,
            word_count=0,
            line_count=0,
            duration=None,
            project_dir=str(project_dir),
            note='Install with: pip install faster-whisper',
        )
        return asdict(result)

    prepared_audio = _prepare_cpu_audio(project_dir, audio_path, force=force)

    model = WhisperModel(model_size, device='cpu', compute_type=compute_type)
    segments_iter, info = model.transcribe(
        str(prepared_audio),
        language=language,
        beam_size=beam_size,
        best_of=beam_size,
        temperature=0.0,
        vad_filter=vad_filter,
        word_timestamps=True,
        condition_on_previous_text=False,
        no_speech_threshold=0.25,
        log_prob_threshold=-1.0,
        compression_ratio_threshold=2.4,
    )

    segments = []
    for seg in segments_iter:
        words = []
        for w in seg.words or []:
            words.append({
                'start': float(w.start),
                'end': float(w.end),
                'word': w.word,
                'probability': float(w.probability) if w.probability is not None else None,
            })
        segments.append({
            'id': getattr(seg, 'id', None),
            'start': float(seg.start),
            'end': float(seg.end),
            'text': seg.text,
            'avg_logprob': getattr(seg, 'avg_logprob', None),
            'no_speech_prob': getattr(seg, 'no_speech_prob', None),
            'words': words,
        })

    words = _words_from_segments(segments)
    seg_lines = _write_segment_lrc(output_segment_lrc, segments)
    word_lines = _write_word_grouped_lrc(output_word_lrc, words)

    data = {
        **signature,
        'word_lrc_sha256': fingerprint(output_word_lrc),
        'segment_lrc_sha256': fingerprint(output_segment_lrc),
        'engine': 'faster-whisper',
        'model_size': model_size,
        'compute_type': compute_type,
        'device': 'cpu',
        'audio': str(audio_path),
        'prepared_audio': str(prepared_audio),
        'language': getattr(info, 'language', language),
        'language_probability': getattr(info, 'language_probability', None),
        'duration': getattr(info, 'duration', None),
        'vad_filter': vad_filter,
        'beam_size': beam_size,
        'segment_count': len(segments),
        'word_count': len(words),
        'segments': segments,
        'words': words,
    }
    _json_dump(output_json, data)

    note = 'Word timestamps generated. Use whisper_word_rough_lrc.lrc for fallback inspection.'
    reason = None
    ok = True
    if len(words) < 8:
        ok = False
        reason = 'Whisper produced too few word timestamps. This is usually because the music mix hides vocals or the track is mostly instrumental.'
        note = 'Try vocal separation before Whisper, or use an external synced lyric source.'

    result = WhisperAdvancedResult(
        ok=ok,
        mode='whisper_advanced_probe',
        reason=reason,
        engine='faster-whisper',
        model_size=model_size,
        compute_type=compute_type,
        language=getattr(info, 'language', language),
        audio=str(audio_path),
        prepared_audio=str(prepared_audio),
        output_json=str(output_json),
        output_word_lrc=str(output_word_lrc),
        output_segment_lrc=str(output_segment_lrc),
        report_path=str(report_path),
        segment_count=len(segments),
        word_count=len(words),
        line_count=word_lines,
        duration=getattr(info, 'duration', None),
        project_dir=str(project_dir),
        note=note,
    )
    _json_dump(report_path, asdict(result))
    return asdict(result)


def main() -> None:
    parser = argparse.ArgumentParser(description='Advanced CPU Whisper probe with word timestamps.')
    parser.add_argument('--project', required=True)
    parser.add_argument('--model', default='medium', help='Recommended CPU accuracy: medium. Faster: small. Slowest/best: large-v3.')
    parser.add_argument('--compute-type', default='int8')
    parser.add_argument('--language', default=None)
    parser.add_argument('--force', action='store_true')
    parser.add_argument('--beam-size', type=int, default=5)
    parser.add_argument('--vad-filter', action='store_true', help='Usually keep off for music; enable only if speech sections are obvious.')
    args = parser.parse_args()

    result = run_advanced_whisper_probe(
        project=args.project,
        model_size=args.model,
        compute_type=args.compute_type,
        language=args.language,
        force=args.force,
        beam_size=args.beam_size,
        vad_filter=args.vad_filter,
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == '__main__':
    main()
