from __future__ import annotations

import json
import re
import shutil
import unicodedata
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from echoforge.stages.verselock.lrc_parser import seconds_to_lrc_timestamp

SECTION_RE = re.compile(r"^\s*\[[^\]]+\]\s*$")
PAREN_RE = re.compile(r"\([^)]*\)|\[[^]]*\]")
PUNCT_RE = re.compile(r"[^a-z0-9 ]+", re.IGNORECASE)
MULTISPACE_RE = re.compile(r"\s+")


@dataclass
class WhisperLine:
    index: int
    start_seconds: float
    end_seconds: float
    text: str
    source_word_start_index: int | None = None
    source_word_end_index: int | None = None


@dataclass
class TransferredLine:
    index: int
    timestamp: str
    start_seconds: float
    start_ms: int
    end_seconds: float | None
    text: str
    whisper_line_index: int
    whisper_text: str
    text_similarity: float
    method: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def _ascii(text: str) -> str:
    return unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode("ascii")


def normalize_text(text: str, *, remove_parenthetical: bool = True) -> str:
    text = _ascii(text).lower().replace("&", " and ")
    if remove_parenthetical:
        text = PAREN_RE.sub(" ", text)
    text = text.replace("'", "")
    text = PUNCT_RE.sub(" ", text)
    return MULTISPACE_RE.sub(" ", text).strip()


def text_similarity(a: str, b: str) -> float:
    a_norm = normalize_text(a)
    b_norm = normalize_text(b)
    if not a_norm or not b_norm:
        return 0.0
    seq = SequenceMatcher(None, a_norm, b_norm).ratio()
    a_set = set(a_norm.split())
    b_set = set(b_norm.split())
    overlap = len(a_set & b_set) / max(len(a_set), 1)
    return round(seq * 0.65 + overlap * 0.35, 4)


def load_lyrics_lines(path: Path) -> list[str]:
    raw = path.read_text(encoding="utf-8", errors="ignore")
    lines: list[str] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        if SECTION_RE.match(line):
            continue
        low = line.lower().strip()
        if low in {"lyrics", "embed", "you might also like"}:
            continue
        if low.endswith("embed") and len(low) < 45:
            continue
        lines.append(line)
    return lines


def load_words(transcript_path: Path) -> list[dict[str, Any]]:
    data = _read_json(transcript_path)
    out: list[dict[str, Any]] = []
    for w in data.get("words") or []:
        word = str(w.get("word") or "").strip()
        if not word:
            continue
        try:
            start = float(w.get("start"))
            end = float(w.get("end"))
        except Exception:
            continue
        out.append({"word": word, "start": start, "end": end, "index": len(out)})
    return out


def load_segments(transcript_path: Path) -> list[dict[str, Any]]:
    data = _read_json(transcript_path)
    out: list[dict[str, Any]] = []
    for seg in data.get("segments") or []:
        try:
            start = float(seg.get("start"))
            end = float(seg.get("end"))
        except Exception:
            continue
        text = str(seg.get("text") or "").strip()
        if text:
            out.append({"start": start, "end": end, "text": text})
    return out


def group_words_into_lines(words: list[dict[str, Any]]) -> list[WhisperLine]:
    """Create a timing skeleton from Whisper words.

    This intentionally does not trust Whisper text. It only uses Whisper to locate
    where sung phrases happen in time. Official lyrics are inserted later.
    """
    if not words:
        return []

    groups: list[WhisperLine] = []
    current: list[dict[str, Any]] = []
    start = float(words[0]["start"])
    last_end = float(words[0]["end"])

    def flush() -> None:
        nonlocal current, start, last_end
        if not current:
            return
        text = " ".join(str(w["word"]).strip() for w in current).strip()
        groups.append(
            WhisperLine(
                index=len(groups),
                start_seconds=round(float(current[0]["start"]), 3),
                end_seconds=round(float(current[-1]["end"]), 3),
                text=text,
                source_word_start_index=int(current[0]["index"]),
                source_word_end_index=int(current[-1]["index"]),
            )
        )
        current = []

    for i, word in enumerate(words):
        w = str(word["word"]).strip()
        gap = float(word["start"]) - float(last_end)
        duration = float(word["end"]) - float(start)
        punctuation_break = w.endswith((".", ",", "?", "!", ";", ":"))
        too_many_words = len(current) >= 7
        too_long = duration >= 4.2
        big_gap = gap >= 0.85

        if current and (too_many_words or too_long or big_gap):
            flush()
            start = float(word["start"])

        current.append(word)
        last_end = float(word["end"])

        if punctuation_break and len(current) >= 3:
            flush()
            if i + 1 < len(words):
                start = float(words[i + 1]["start"])

    flush()
    return groups


def _segments_as_lines(segments: list[dict[str, Any]]) -> list[WhisperLine]:
    return [
        WhisperLine(index=i, start_seconds=round(float(s["start"]), 3), end_seconds=round(float(s["end"]), 3), text=str(s["text"]))
        for i, s in enumerate(segments)
    ]


def _choose_whisper_line(
    lyric: str,
    lyric_index: int,
    lyric_count: int,
    whisper_lines: list[WhisperLine],
    last_chosen: int,
    *,
    snap_window: int = 4,
) -> tuple[WhisperLine, float, str]:
    if not whisper_lines:
        return WhisperLine(0, 0.0, 0.0, ""), 0.0, "zero_fallback"

    if lyric_count <= 1:
        expected = 0
    else:
        expected = round(lyric_index * (len(whisper_lines) - 1) / (lyric_count - 1))
    expected = max(last_chosen, min(expected, len(whisper_lines) - 1))

    # Look around the proportional location. If text similarity is useful, snap;
    # otherwise keep the proportional timestamp. This handles "dai" heard as "die".
    start = max(last_chosen, expected - snap_window)
    end = min(len(whisper_lines) - 1, expected + snap_window)
    best = whisper_lines[expected]
    best_score = text_similarity(lyric, best.text)
    best_pos_penalty = 0.0
    for j in range(start, end + 1):
        sim = text_similarity(lyric, whisper_lines[j].text)
        pos_penalty = abs(j - expected) / max(snap_window, 1) * 0.08
        adjusted = sim - pos_penalty
        if adjusted > best_score - best_pos_penalty:
            best = whisper_lines[j]
            best_score = sim
            best_pos_penalty = pos_penalty

    method = "similarity_snap" if best.index != expected and best_score >= 0.42 else "proportional_timestamp_transfer"
    if method == "proportional_timestamp_transfer":
        best = whisper_lines[expected]
        best_score = text_similarity(lyric, best.text)
    return best, round(best_score, 4), method


def _enforce_monotonic(lines: list[TransferredLine]) -> None:
    last = -0.01
    for line in lines:
        if line.start_seconds <= last:
            line.start_seconds = round(last + 0.15, 3)
            line.start_ms = int(round(line.start_seconds * 1000))
            line.timestamp = seconds_to_lrc_timestamp(line.start_seconds)
        last = line.start_seconds


def _lines_to_lrc(lines: list[TransferredLine]) -> str:
    return "\n".join(f"[{line.timestamp}] {line.text}" for line in lines).strip() + "\n"


def timestamp_transfer_sync(
    project: str | Path,
    *,
    transcript_path: str | Path | None = None,
    lyrics_path: str | Path | None = None,
    force: bool = False,
    promote: bool = False,
    use_segments: bool = False,
) -> dict[str, Any]:
    """Transfer Whisper timing skeleton onto official lyrics.

    This is different from text alignment. We accept that Whisper may hear wrong
    letters/words, and we only use its timestamps. The output text comes from
    lyrics.txt.
    """
    project_dir = Path(project)
    sync_dir = project_dir / "sync"
    candidate_dir = sync_dir / "candidates"
    transcript_path = Path(transcript_path) if transcript_path else sync_dir / "whisper_advanced_transcript.json"
    lyrics_path = Path(lyrics_path) if lyrics_path else project_dir / "lyrics" / "lyrics.txt"
    final_lrc = sync_dir / "final_synced_lyrics.lrc"
    final_json = sync_dir / "final_synced_lyrics.json"
    candidate_lrc = candidate_dir / "timestamp_transfer_candidate.lrc"
    candidate_json = candidate_dir / "timestamp_transfer_candidate.json"
    report_path = sync_dir / "timestamp_transfer_report.json"

    if not lyrics_path.exists():
        result = {"ok": False, "mode": "timestamp_transfer_sync", "reason": f"lyrics.txt not found: {lyrics_path}", "project_dir": str(project_dir)}
        _write_json(report_path, result)
        return result
    if not transcript_path.exists():
        result = {"ok": False, "mode": "timestamp_transfer_sync", "reason": f"Whisper transcript not found: {transcript_path}", "project_dir": str(project_dir)}
        _write_json(report_path, result)
        return result

    lyric_lines = load_lyrics_lines(lyrics_path)
    words = load_words(transcript_path)
    segments = load_segments(transcript_path)
    whisper_lines = _segments_as_lines(segments) if use_segments else group_words_into_lines(words)
    if not whisper_lines and segments:
        whisper_lines = _segments_as_lines(segments)
    if not lyric_lines:
        result = {"ok": False, "mode": "timestamp_transfer_sync", "reason": "No usable lyric lines found.", "project_dir": str(project_dir)}
        _write_json(report_path, result)
        return result
    if not whisper_lines:
        result = {"ok": False, "mode": "timestamp_transfer_sync", "reason": "No Whisper timing skeleton found.", "project_dir": str(project_dir)}
        _write_json(report_path, result)
        return result

    transferred: list[TransferredLine] = []
    last_chosen = 0
    snapped = 0
    similarities: list[float] = []

    for i, lyric in enumerate(lyric_lines):
        chosen, sim, method = _choose_whisper_line(lyric, i, len(lyric_lines), whisper_lines, last_chosen)
        if method == "similarity_snap":
            snapped += 1
        similarities.append(sim)
        transferred.append(
            TransferredLine(
                index=i,
                timestamp=seconds_to_lrc_timestamp(chosen.start_seconds),
                start_seconds=round(chosen.start_seconds, 3),
                start_ms=int(round(chosen.start_seconds * 1000)),
                end_seconds=round(chosen.end_seconds, 3) if chosen.end_seconds is not None else None,
                text=lyric,
                whisper_line_index=chosen.index,
                whisper_text=chosen.text,
                text_similarity=sim,
                method=method,
            )
        )
        last_chosen = max(last_chosen, chosen.index)

    _enforce_monotonic(transferred)
    avg_sim = round(sum(similarities) / max(len(similarities), 1), 4)
    count_ratio = round(min(len(lyric_lines), len(whisper_lines)) / max(len(lyric_lines), len(whisper_lines), 1), 4)

    payload = {
        "schema": "echoforge.final_synced_lyrics.timestamp_transfer.v1",
        "source": "official_lyrics_plus_whisper_timing_skeleton",
        "created_at": now_iso(),
        "project_dir": str(project_dir),
        "lyrics_path": str(lyrics_path),
        "whisper_transcript": str(transcript_path),
        "line_count": len(transferred),
        "lyrics_line_count": len(lyric_lines),
        "whisper_line_count": len(whisper_lines),
        "whisper_word_count": len(words),
        "whisper_segment_count": len(segments),
        "line_count_ratio": count_ratio,
        "average_text_similarity": avg_sim,
        "snapped_by_similarity": snapped,
        "note": "Text comes from lyrics.txt. Timestamps come from Whisper timing skeleton. Low text similarity is acceptable here when pronunciation differs.",
        "lines": [x.to_dict() for x in transferred],
    }

    ok = len(transferred) > 0 and len(whisper_lines) >= max(8, int(len(lyric_lines) * 0.55))
    output_lrc = final_lrc if promote else candidate_lrc
    output_json = final_json if promote else candidate_json
    output_lrc.parent.mkdir(parents=True, exist_ok=True)
    output_lrc.write_text(_lines_to_lrc(transferred), encoding="utf-8")
    _write_json(output_json, payload)

    result = {
        "ok": ok,
        "mode": "timestamp_transfer_sync",
        "reason": None if ok else "Whisper timing skeleton is too sparse for timestamp transfer.",
        "promoted_to_final": bool(promote),
        "output_lrc": str(output_lrc),
        "output_json": str(output_json),
        "final_lrc": str(final_lrc),
        "final_json": str(final_json),
        "report_path": str(report_path),
        "lyrics_line_count": len(lyric_lines),
        "whisper_line_count": len(whisper_lines),
        "whisper_word_count": len(words),
        "whisper_segment_count": len(segments),
        "line_count_ratio": count_ratio,
        "average_text_similarity": avg_sim,
        "snapped_by_similarity": snapped,
        "candidate_only": not promote,
        "project_dir": str(project_dir),
        "note": "Inspect timestamp_transfer_candidate.lrc. If it looks good, rerun with --promote.",
    }
    _write_json(report_path, result)
    return result
