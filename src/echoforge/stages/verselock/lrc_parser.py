from __future__ import annotations

import re
from dataclasses import dataclass, asdict
from pathlib import Path

TIMESTAMP_RE = re.compile(r"\[(\d{1,2}):(\d{2})(?:[.:](\d{1,3}))?\]")
METADATA_RE = re.compile(r"\[[a-zA-Z]+:.*?\]")


@dataclass
class LrcLine:
    index: int
    timestamp: str
    start_seconds: float
    start_ms: int
    text: str

    def to_dict(self) -> dict:
        return asdict(self)


def _fraction_to_ms(value: str | None) -> int:
    if not value:
        return 0
    value = value[:3].ljust(3, "0")
    return int(value)


def timestamp_to_seconds(minutes: str, seconds: str, fraction: str | None) -> float:
    return int(minutes) * 60 + int(seconds) + (_fraction_to_ms(fraction) / 1000.0)


def seconds_to_lrc_timestamp(seconds: float) -> str:
    total_ms = max(int(round(seconds * 1000)), 0)
    minutes = total_ms // 60000
    remaining = total_ms % 60000
    secs = remaining // 1000
    hundredths = (remaining % 1000) // 10
    return f"{minutes:02d}:{secs:02d}.{hundredths:02d}"


def parse_lrc_text(raw_text: str) -> list[LrcLine]:
    parsed: list[LrcLine] = []
    line_index = 0

    for raw_line in raw_text.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        matches = list(TIMESTAMP_RE.finditer(line))
        if not matches:
            continue

        text = TIMESTAMP_RE.sub("", line).strip()
        text = METADATA_RE.sub("", text).strip()
        if not text:
            continue

        for match in matches:
            start = timestamp_to_seconds(match.group(1), match.group(2), match.group(3))
            parsed.append(
                LrcLine(
                    index=line_index,
                    timestamp=seconds_to_lrc_timestamp(start),
                    start_seconds=round(start, 3),
                    start_ms=int(round(start * 1000)),
                    text=text,
                )
            )
            line_index += 1

    parsed.sort(key=lambda item: item.start_ms)
    for idx, item in enumerate(parsed):
        item.index = idx
    return parsed


def parse_lrc_file(path: str | Path) -> list[LrcLine]:
    return parse_lrc_text(Path(path).read_text(encoding="utf-8", errors="ignore"))


def lines_to_lrc(lines: list[LrcLine]) -> str:
    return "\n".join(f"[{line.timestamp}] {line.text}" for line in lines).strip() + "\n"
