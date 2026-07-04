from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


class StageName(str, Enum):
    SONGSCOUT = "songscout"
    MUSEVAULT = "musevault"
    VERSELOCK = "verselock"
    WEBEDITOR = "webeditor"
    RENDERER = "renderer"
    TUBEHARBOR = "tubeharbor"


class StageStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    NEEDS_REVIEW = "needs_review"
    SKIPPED = "skipped"


@dataclass
class SongCandidate:
    title: str
    artist: str
    rank: int | None = None
    youtube_url: str | None = None
    thumbnail_url: str | None = None
    source: str = "youtube_charts"


@dataclass
class ProjectState:
    project_id: str
    title: str
    artist: str
    project_dir: Path

    current_stage: StageName = StageName.SONGSCOUT

    stages: dict[str, str] = field(
        default_factory=lambda: {
            StageName.SONGSCOUT.value: StageStatus.PENDING.value,
            StageName.MUSEVAULT.value: StageStatus.PENDING.value,
            StageName.VERSELOCK.value: StageStatus.PENDING.value,
            StageName.WEBEDITOR.value: StageStatus.PENDING.value,
            StageName.RENDERER.value: StageStatus.PENDING.value,
            StageName.TUBEHARBOR.value: StageStatus.PENDING.value,
        }
    )

    metadata: dict[str, Any] = field(default_factory=dict)

    def mark_stage(self, stage: StageName, status: StageStatus) -> None:
        self.stages[stage.value] = status.value
        self.current_stage = stage