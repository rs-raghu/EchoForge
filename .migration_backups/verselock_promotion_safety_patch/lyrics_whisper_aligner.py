from __future__ import annotations

import json
import re
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

WORD_EXPANSIONS = {
    "gonna": "going to",
    "wanna": "want to",
    "gotta": "got to",
    "im": "i am",
    "youre": "you are",
    "youve": "you have",
    "dont": "do not",
    "cant": "can not",
    "wont": "will not",
    "aint": "is not",
}


@dataclass
class AlignedLine:
    index: int
    timestamp: str
    start_seconds: float
    start_ms: int
    end_seconds: float | None
    text: str
    confidence: float
    method: str
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


def _ascii(text: str) -> str:
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")


def normalize_for_match(text: str, *, strip_parenthetical: bool = True) -> str:
    text = _ascii(text or "").lower().replace("&", " and ")
    text = text.replace("'", "")
    if strip_parenthetical:
        text = PAREN_RE.sub(" ", text)
    text = PUNCT_RE.sub(" ", text)
    text = MULTISPACE_RE.sub(" ", text).strip()
    for src, dst in WORD_EXPANSIONS.items():
        text = re.sub(rf"\b{re.escape(src)}\b", dst, text)
    return MULTISPACE_RE.sub(" ", text).strip()


def tokenize(text: str) -> list[str]:
    return [x for x in normalize_for_match(text).split(" ") if x]


def load_lyrics_lines(path: Path) -> list[str]:
    raw = path.read_text(encoding="utf-8", errors="ignore")
    out: list[str] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line or SECTION_RE.match(line):
            continue
        low = line.lower().strip()
        if low in {"lyrics", "embed", "you might also like"}:
            continue
        if low.endswith("embed") and len(low) < 45:
            continue
        out.append(line)
    return out


def _word_record(word: str, start: float, end: float, idx: int) -> dict[str, Any]:
    norm = normalize_for_match(word, strip_parenthetical=False)
    parts = [p for p in norm.split(" ") if p]
    # Usually one word, but expansions can create two; keep display word and first normalized token.
    token = parts[0] if parts else ""
    return {"word": word, "token": token, "start": start, "end": end, "index": idx}


def load_words(transcript_path: Path) -> list[dict[str, Any]]:
    data = read_json(transcript_path)
    raw_words = data.get("words") or []
    clean: list[dict[str, Any]] = []
    for w in raw_words:
        word = str(w.get("word") or "").strip()
        if not word:
            continue
        try:
            start = float(w.get("start"))
            end = float(w.get("end"))
        except Exception:
            continue
        rec = _word_record(word, start, end, len(clean))
        if rec["token"]:
            clean.append(rec)
    return clean


def load_segments(transcript_path: Path) -> list[dict[str, Any]]:
    data = read_json(transcript_path)
    segments = data.get("segments") or []
    out: list[dict[str, Any]] = []
    for seg in segments:
        try:
            start = float(seg.get("start"))
            end = float(seg.get("end"))
        except Exception:
            continue
        text = str(seg.get("text") or "").strip()
        if text:
            out.append({"start": start, "end": end, "text": text})
    return out


def _ordered_coverage(needle: list[str], haystack: list[str]) -> float:
    if not needle:
        return 0.0
    pos = 0
    hit = 0
    for tok in needle:
        found = False
        while pos < len(haystack):
            if tok == haystack[pos]:
                found = True
                pos += 1
                break
            pos += 1
        if found:
            hit += 1
    return hit / max(len(needle), 1)


def _candidate_score(lyric_tokens: list[str], candidate_words: list[dict[str, Any]]) -> float:
    cand_tokens = [str(w.get("token") or "") for w in candidate_words if w.get("token")]
    lyric_text = " ".join(lyric_tokens)
    cand_text = " ".join(cand_tokens)
    if not lyric_text or not cand_text:
        return 0.0
    seq = SequenceMatcher(None, lyric_text, cand_text).ratio()
    lyric_set = set(lyric_tokens)
    cand_set = set(cand_tokens)
    overlap = len(lyric_set & cand_set) / max(len(lyric_set), 1)
    ordered = _ordered_coverage(lyric_tokens, cand_tokens)
    len_ratio = min(len(cand_tokens), len(lyric_tokens)) / max(len(cand_tokens), len(lyric_tokens), 1)
    return round((seq * 0.35 + overlap * 0.25 + ordered * 0.3 + len_ratio * 0.1), 4)


def _find_best_window(
    lyric_tokens: list[str],
    words: list[dict[str, Any]],
    cursor: int,
    *,
    search_ahead: int = 180,
) -> tuple[int | None, int | None, float]:
    if not lyric_tokens or not words:
        return None, None, 0.0
    n = max(len(lyric_tokens), 1)
    min_len = max(1, int(n * 0.55))
    max_len = min(max(n + 8, int(n * 2.4)), 34)
    start_min = max(0, cursor - 8)
    start_max = min(len(words), cursor + search_ahead)
    best: tuple[int | None, int | None, float] = (None, None, 0.0)
    for start in range(start_min, start_max):
        for length in range(min_len, max_len + 1):
            end = min(start + length, len(words))
            if end <= start:
                continue
            score = _candidate_score(lyric_tokens, words[start:end])
            # Slight penalty for jumping too far ahead; helps keep sequence stable.
            jump = max(0, start - cursor)
            if jump > 40:
                score *= 0.96
            if score > best[2]:
                best = (start, end - 1, round(score, 4))
    return best


def _segment_index_fallback(index: int, lyric_count: int, segments: list[dict[str, Any]], words: list[dict[str, Any]]) -> tuple[float, float | None, str]:
    if segments:
        seg_i = min(len(segments) - 1, round(index * max(len(segments) - 1, 0) / max(lyric_count - 1, 1)))
        seg = segments[seg_i]
        return float(seg["start"]), float(seg["end"]), "segment_index_fallback"
    if words:
        word_i = min(len(words) - 1, round(index * max(len(words) - 1, 0) / max(lyric_count - 1, 1)))
        return float(words[word_i]["start"]), float(words[word_i]["end"]), "word_index_fallback"
    return 0.0, None, "zero_fallback"


def _enforce_monotonic(lines: list[AlignedLine]) -> None:
    last = -0.01
    for line in lines:
        if line.start_seconds <= last:
            line.start_seconds = round(last + 0.15, 3)
            line.start_ms = int(round(line.start_seconds * 1000))
            line.timestamp = seconds_to_lrc_timestamp(line.start_seconds)
        last = line.start_seconds


def lines_to_lrc(lines: list[AlignedLine]) -> str:
    return "\n".join(f"[{line.timestamp}] {line.text}" for line in lines).strip() + "\n"


def source_match_report(project_dir: Path, lyric_lines: list[str], words: list[dict[str, Any]], segments: list[dict[str, Any]]) -> dict[str, Any]:
    lyrics_text = normalize_for_match(" ".join(lyric_lines))
    whisper_text = normalize_for_match(" ".join(str(w["word"]) for w in words), strip_parenthetical=False)
    ratio = SequenceMatcher(None, lyrics_text[:12000], whisper_text[:12000]).ratio() if lyrics_text and whisper_text else 0.0
    lyric_tokens = set(lyrics_text.split())
    whisper_tokens = set(whisper_text.split())
    overlap = len(lyric_tokens & whisper_tokens) / max(len(lyric_tokens), 1) if lyric_tokens else 0.0
    report = {
        "lyrics_line_count": len(lyric_lines),
        "whisper_word_count": len(words),
        "whisper_segment_count": len(segments),
        "global_text_similarity": round(ratio, 4),
        "lyrics_token_overlap_in_whisper": round(overlap, 4),
        "lyrics_preview": lyric_lines[:12],
        "whisper_preview": " ".join(str(w["word"]) for w in words[:120]),
        "warning": None,
    }
    if overlap < 0.35:
        report["warning"] = "lyrics.txt and Whisper transcript appear to be weakly related. This usually means wrong lyrics source, different version, multilingual transcription mismatch, or heavy music/vocal interference."
    return report


def align_lyrics_to_whisper(
    project: str | Path,
    *,
    transcript_path: str | Path | None = None,
    lyrics_path: str | Path | None = None,
    force: bool = False,
    min_confidence: float = 0.32,
    promote_threshold: float = 0.22,
    safe_candidate_on_low_confidence: bool = True,
) -> dict[str, Any]:
    project_dir = Path(project)
    lyrics_path = Path(lyrics_path) if lyrics_path else project_dir / "lyrics" / "lyrics.txt"
    transcript_path = Path(transcript_path) if transcript_path else project_dir / "sync" / "whisper_advanced_transcript.json"
    sync_dir = project_dir / "sync"
    candidate_dir = sync_dir / "candidates"
    final_lrc = sync_dir / "final_synced_lyrics.lrc"
    final_json = sync_dir / "final_synced_lyrics.json"
    candidate_lrc = candidate_dir / "whisper_alignment_v2_candidate.lrc"
    candidate_json = candidate_dir / "whisper_alignment_v2_candidate.json"
    report_path = sync_dir / "whisper_alignment_v2_report.json"

    if final_lrc.exists() and final_json.exists() and not force:
        result = {
            "ok": True,
            "mode": "reuse_existing_final_sync",
            "reason": None,
            "output_lrc": str(final_lrc),
            "output_json": str(final_json),
            "report_path": str(report_path),
            "project_dir": str(project_dir),
        }
        write_json(report_path, result)
        return result

    if not lyrics_path.exists():
        result = {"ok": False, "mode": "whisper_alignment_v2", "reason": f"lyrics.txt not found: {lyrics_path}", "project_dir": str(project_dir)}
        write_json(report_path, result)
        return result
    if not transcript_path.exists():
        result = {"ok": False, "mode": "whisper_alignment_v2", "reason": f"Whisper transcript not found: {transcript_path}", "project_dir": str(project_dir)}
        write_json(report_path, result)
        return result

    lyric_lines = load_lyrics_lines(lyrics_path)
    words = load_words(transcript_path)
    segments = load_segments(transcript_path)
    if not lyric_lines:
        result = {"ok": False, "mode": "whisper_alignment_v2", "reason": "No usable lyric lines found.", "project_dir": str(project_dir)}
        write_json(report_path, result)
        return result
    if not words:
        result = {"ok": False, "mode": "whisper_alignment_v2", "reason": "No Whisper word timestamps found.", "project_dir": str(project_dir)}
        write_json(report_path, result)
        return result

    source_report = source_match_report(project_dir, lyric_lines, words, segments)
    aligned: list[AlignedLine] = []
    cursor = 0
    low_confidence = []
    matched = 0

    for idx, lyric in enumerate(lyric_lines):
        ltoks = tokenize(lyric)
        start_i, end_i, score = _find_best_window(ltoks, words, cursor)
        method = "word_fuzzy_window"
        if start_i is None or end_i is None or score < min_confidence:
            start_s, end_s, method = _segment_index_fallback(idx, len(lyric_lines), segments, words)
            score = round(score or 0.0, 4)
            low_confidence.append({"index": idx, "text": lyric, "confidence": score, "fallback_method": method})
            start_i = None
            end_i = None
        else:
            matched += 1
            start_s = float(words[start_i]["start"])
            end_s = float(words[end_i]["end"])
            cursor = min(len(words) - 1, max(end_i + 1, cursor + 1))

        aligned.append(
            AlignedLine(
                index=idx,
                timestamp=seconds_to_lrc_timestamp(start_s),
                start_seconds=round(start_s, 3),
                start_ms=int(round(start_s * 1000)),
                end_seconds=round(end_s, 3) if end_s is not None else None,
                text=lyric,
                confidence=score,
                method=method,
                source_word_start_index=start_i,
                source_word_end_index=end_i,
            )
        )

    _enforce_monotonic(aligned)
    avg_conf = round(sum(x.confidence for x in aligned) / max(len(aligned), 1), 4)
    matched_ratio = round(matched / max(len(aligned), 1), 4)

    payload = {
        "schema": "echoforge.final_synced_lyrics.v2",
        "source": "whisper_advanced_word_alignment_v2",
        "created_at": now_iso(),
        "project_dir": str(project_dir),
        "lyrics_path": str(lyrics_path),
        "whisper_transcript": str(transcript_path),
        "line_count": len(aligned),
        "matched_lines": matched,
        "matched_ratio": matched_ratio,
        "low_confidence_count": len(low_confidence),
        "average_confidence": avg_conf,
        "source_match_report": source_report,
        "lines": [line.to_dict() for line in aligned],
    }

    # Safety rule: poor fallback should not overwrite a good LRCLIB final file.
    promote = avg_conf >= promote_threshold and matched_ratio >= 0.25 and source_report.get("lyrics_token_overlap_in_whisper", 0) >= 0.25
    if promote or not safe_candidate_on_low_confidence:
        output_lrc = final_lrc
        output_json = final_json
    else:
        output_lrc = candidate_lrc
        output_json = candidate_json

    output_lrc.parent.mkdir(parents=True, exist_ok=True)
    output_lrc.write_text(lines_to_lrc(aligned), encoding="utf-8")
    write_json(output_json, payload)

    ok = bool(promote)
    reason = None if ok else "Fallback alignment is weak. Candidate output was created but not promoted to final sync."
    result = {
        "ok": ok,
        "mode": "whisper_alignment_v2",
        "reason": reason,
        "promoted_to_final": promote,
        "output_lrc": str(output_lrc),
        "output_json": str(output_json),
        "final_lrc": str(final_lrc),
        "final_json": str(final_json),
        "report_path": str(report_path),
        "lyrics_lines": len(lyric_lines),
        "word_count": len(words),
        "segment_count": len(segments),
        "line_count": len(aligned),
        "matched_lines": matched,
        "matched_ratio": matched_ratio,
        "low_confidence_count": len(low_confidence),
        "average_confidence": avg_conf,
        "source_match_report": source_report,
        "low_confidence_samples": low_confidence[:12],
        "project_dir": str(project_dir),
        "note": "V2 creates a safe candidate when lyric/source mismatch is likely. Use LRCLIB output when available.",
    }
    write_json(report_path, result)
    return result
