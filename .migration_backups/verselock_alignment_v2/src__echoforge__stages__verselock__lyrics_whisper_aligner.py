from __future__ import annotations

import json
import re
import shutil
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from echoforge.stages.verselock.lrc_parser import seconds_to_lrc_timestamp

SECTION_RE = re.compile(r"^\s*\[[^\]]+\]\s*$")
PUNCT_RE = re.compile(r"[^a-z0-9' ]+", re.IGNORECASE)
MULTISPACE_RE = re.compile(r"\s+")


@dataclass
class AlignedLine:
    index: int
    timestamp: str
    start_seconds: float
    start_ms: int
    end_seconds: float | None
    text: str
    confidence: float
    source_word_start_index: int | None
    source_word_end_index: int | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def normalize_for_match(text: str) -> str:
    text = text.lower().replace("&", " and ")
    text = PUNCT_RE.sub(" ", text)
    return MULTISPACE_RE.sub(" ", text).strip()


def tokenize(text: str) -> list[str]:
    cleaned = normalize_for_match(text)
    return [x for x in cleaned.split(" ") if x]


def load_lyrics_lines(path: Path) -> list[str]:
    raw = path.read_text(encoding="utf-8", errors="ignore")
    out: list[str] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        if SECTION_RE.match(line):
            continue
        low = line.lower().strip()
        if low in {"lyrics", "embed", "you might also like"}:
            continue
        if low.endswith("embed") and len(low) < 40:
            continue
        out.append(line)
    return out


def load_words(transcript_path: Path) -> list[dict[str, Any]]:
    data = read_json(transcript_path)
    words = data.get("words") or []
    clean = []
    for w in words:
        word = str(w.get("word") or "").strip()
        if not word:
            continue
        try:
            start = float(w.get("start"))
            end = float(w.get("end"))
        except Exception:
            continue
        clean.append({"word": word, "start": start, "end": end})
    return clean


def _candidate_score(lyric_tokens: list[str], candidate_words: list[dict[str, Any]]) -> float:
    cand_text = " ".join(tokenize(" ".join(str(w["word"]) for w in candidate_words)))
    lyric_text = " ".join(lyric_tokens)
    if not lyric_text or not cand_text:
        return 0.0
    seq = SequenceMatcher(None, lyric_text, cand_text).ratio()
    lyric_set = set(lyric_tokens)
    cand_set = set(cand_text.split())
    overlap = len(lyric_set & cand_set) / max(len(lyric_set), 1)
    length_penalty = 1.0 - min(abs(len(candidate_words) - len(lyric_tokens)) / max(len(lyric_tokens), 1), 1.0) * 0.25
    return round((seq * 0.65 + overlap * 0.35) * length_penalty, 4)


def _find_best_window(
    lyric_tokens: list[str],
    words: list[dict[str, Any]],
    cursor: int,
    *,
    search_ahead: int = 90,
) -> tuple[int | None, int | None, float]:
    if not lyric_tokens or not words:
        return None, None, 0.0
    n = max(len(lyric_tokens), 1)
    min_len = max(1, int(n * 0.55))
    max_len = min(max(n + 5, int(n * 1.6)), 22)
    start_max = min(len(words), cursor + search_ahead)
    best: tuple[int | None, int | None, float] = (None, None, 0.0)
    for start in range(cursor, start_max):
        for length in range(min_len, max_len + 1):
            end = min(start + length, len(words))
            if end <= start:
                continue
            score = _candidate_score(lyric_tokens, words[start:end])
            if score > best[2]:
                best = (start, end - 1, score)
    return best


def lines_to_lrc(lines: list[AlignedLine]) -> str:
    return "\n".join(f"[{line.timestamp}] {line.text}" for line in lines).strip() + "\n"


def align_lyrics_to_whisper(
    project: str | Path,
    *,
    transcript_path: str | Path | None = None,
    lyrics_path: str | Path | None = None,
    force: bool = False,
    min_confidence: float = 0.23,
) -> dict[str, Any]:
    project_dir = Path(project)
    lyrics_path = Path(lyrics_path) if lyrics_path else project_dir / "lyrics" / "lyrics.txt"
    transcript_path = Path(transcript_path) if transcript_path else project_dir / "sync" / "whisper_advanced_transcript.json"
    sync_dir = project_dir / "sync"
    output_lrc = sync_dir / "final_synced_lyrics.lrc"
    output_json = sync_dir / "final_synced_lyrics.json"
    report_path = sync_dir / "whisper_alignment_report.json"

    if output_lrc.exists() and output_json.exists() and not force:
        result = {
            "ok": True,
            "mode": "reuse_existing_final_sync",
            "reason": None,
            "output_lrc": str(output_lrc),
            "output_json": str(output_json),
            "report_path": str(report_path),
            "project_dir": str(project_dir),
        }
        write_json(report_path, result)
        return result

    if not lyrics_path.exists():
        result = {
            "ok": False,
            "mode": "whisper_alignment",
            "reason": f"lyrics.txt not found: {lyrics_path}",
            "project_dir": str(project_dir),
        }
        write_json(report_path, result)
        return result
    if not transcript_path.exists():
        result = {
            "ok": False,
            "mode": "whisper_alignment",
            "reason": f"Whisper transcript not found: {transcript_path}",
            "project_dir": str(project_dir),
        }
        write_json(report_path, result)
        return result

    lyric_lines = load_lyrics_lines(lyrics_path)
    words = load_words(transcript_path)
    if not lyric_lines:
        result = {"ok": False, "mode": "whisper_alignment", "reason": "No usable lyric lines found.", "project_dir": str(project_dir)}
        write_json(report_path, result)
        return result
    if not words:
        result = {"ok": False, "mode": "whisper_alignment", "reason": "No Whisper word timestamps found.", "project_dir": str(project_dir)}
        write_json(report_path, result)
        return result

    aligned: list[AlignedLine] = []
    cursor = 0
    low_confidence = []
    matched = 0

    for idx, lyric in enumerate(lyric_lines):
        ltoks = tokenize(lyric)
        start_i, end_i, score = _find_best_window(ltoks, words, cursor)
        if start_i is None or end_i is None or score < min_confidence:
            # Controlled fallback: place the line near the current cursor so output remains editable.
            fallback_i = min(cursor, len(words) - 1)
            start_i = fallback_i
            advance = max(1, min(len(ltoks), 8))
            end_i = min(len(words) - 1, fallback_i + advance - 1)
            score = round(score, 4)
            low_confidence.append({"index": idx, "text": lyric, "confidence": score})
        else:
            matched += 1

        start_s = float(words[start_i]["start"])
        end_s = float(words[end_i]["end"])
        aligned.append(
            AlignedLine(
                index=idx,
                timestamp=seconds_to_lrc_timestamp(start_s),
                start_seconds=round(start_s, 3),
                start_ms=int(round(start_s * 1000)),
                end_seconds=round(end_s, 3),
                text=lyric,
                confidence=score,
                source_word_start_index=start_i,
                source_word_end_index=end_i,
            )
        )
        cursor = min(len(words) - 1, max(end_i + 1, cursor + 1))

    sync_dir.mkdir(parents=True, exist_ok=True)
    output_lrc.write_text(lines_to_lrc(aligned), encoding="utf-8")
    avg_conf = round(sum(x.confidence for x in aligned) / max(len(aligned), 1), 4)
    payload = {
        "schema": "echoforge.final_synced_lyrics.v1",
        "source": "whisper_advanced_word_alignment",
        "created_at": now_iso(),
        "project_dir": str(project_dir),
        "lyrics_path": str(lyrics_path),
        "whisper_transcript": str(transcript_path),
        "line_count": len(aligned),
        "matched_lines": matched,
        "low_confidence_count": len(low_confidence),
        "average_confidence": avg_conf,
        "lines": [line.to_dict() for line in aligned],
    }
    write_json(output_json, payload)

    ok = len(aligned) > 0 and avg_conf >= 0.18
    result = {
        "ok": ok,
        "mode": "whisper_alignment",
        "reason": None if ok else "Low average alignment confidence. Output was created but needs manual review.",
        "output_lrc": str(output_lrc),
        "output_json": str(output_json),
        "report_path": str(report_path),
        "lyrics_lines": len(lyric_lines),
        "word_count": len(words),
        "line_count": len(aligned),
        "matched_lines": matched,
        "low_confidence_count": len(low_confidence),
        "average_confidence": avg_conf,
        "low_confidence_samples": low_confidence[:12],
        "project_dir": str(project_dir),
        "note": "This aligns clean lyrics.txt lines to Whisper word timestamps. Review low-confidence lines before rendering.",
    }
    write_json(report_path, result)
    return result
