from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Self, TypedDict, Unpack

# 词时间可比媒体时长多出的秒数，吸收转码和探测时长之间的舍入误差。
TIMELINE_TOLERANCE = 0.001


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class JobStage(StrEnum):
    DOWNLOADING = "downloading"
    PREPARING_AUDIO = "preparingAudio"
    TRANSCRIBING = "transcribing"
    SEGMENTING = "segmenting"


class SubtitleSource(StrEnum):
    AUTO = "auto"
    EXISTING = "existing"
    ASR = "asr"


@dataclass(frozen=True, slots=True)
class Problem:
    code: str
    detail: str


@dataclass(frozen=True, slots=True)
class Word:
    start: float
    end: float
    text: str
    probability: float | None = None

    def __post_init__(self) -> None:
        # 在领域对象构造边界拒绝非法时间，后续算法无需重复防御。
        if self.start < 0:
            raise ValueError("word start must be non-negative")
        if self.end <= self.start:
            raise ValueError("word end must be greater than start")
        if not self.text:
            raise ValueError("word text must not be empty")


@dataclass(frozen=True, slots=True)
class Transcript:
    words: tuple[Word, ...]
    language: str | None
    duration: float
    source: str

    def __post_init__(self) -> None:
        if self.duration <= 0:
            raise ValueError("transcript duration must be positive")
        previous = -1.0
        # 允许词之间有停顿，但不允许时间轴倒退或越过媒体末尾。
        for word in self.words:
            if word.start < previous:
                raise ValueError("word timeline must be monotonic")
            if word.end > self.duration + TIMELINE_TOLERANCE:
                raise ValueError("word exceeds transcript duration")
            previous = word.start


@dataclass(frozen=True, slots=True)
class Sentence:
    index: int
    start: float
    end: float
    speech_start: float
    speech_end: float
    text: str
    words: tuple[Word, ...]

    def __post_init__(self) -> None:
        valid = 0 <= self.start <= self.speech_start < self.speech_end <= self.end
        if not valid:
            raise ValueError("invalid sentence boundaries")
        if self.index < 0:
            raise ValueError("sentence index must be non-negative")

    @property
    def duration(self) -> float:
        return self.end - self.start


@dataclass(frozen=True, slots=True)
class SegmentationOptions:
    min_duration: float = 1.0
    max_duration: float = 30.0
    hard_pause: float = 0.75
    lead_pad: float = 0.30
    tail_pad: float = 0.40
    min_words: int = 2

    def __post_init__(self) -> None:
        if not 0.2 <= self.min_duration <= 10:
            raise ValueError("min_duration must be between 0.2 and 10")
        if not 2 <= self.max_duration <= 60:
            raise ValueError("max_duration must be between 2 and 60")
        if self.min_duration >= self.max_duration:
            raise ValueError("min_duration must be lower than max_duration")
        if not 0.1 <= self.hard_pause <= 5:
            raise ValueError("hard_pause must be between 0.1 and 5")
        if not 0 <= self.lead_pad <= 2 or not 0 <= self.tail_pad <= 2:
            raise ValueError("padding must be between 0 and 2")
        if self.min_words < 1:
            raise ValueError("min_words must be positive")


@dataclass(frozen=True, slots=True)
class JobOptions:
    asr_backend: str
    asr_model: str
    language: str | None
    subtitle_source: SubtitleSource
    subtitle_languages: tuple[str, ...]
    make_clips: bool
    segmentation: SegmentationOptions


class JobChanges(TypedDict, total=False):
    # 状态迁移时允许一并更新的字段；id、创建时间与状态本身不在此列。
    stage: JobStage | None
    progress: float
    message: str
    error: Problem | None
    sentence_count: int
    options: JobOptions | None


@dataclass(frozen=True, slots=True)
class Job:
    id: str
    source: str
    title: str
    status: JobStatus
    stage: JobStage | None
    progress: float
    message: str
    error: Problem | None
    created_at: datetime
    updated_at: datetime
    sentence_count: int
    options: JobOptions | None = None

    @classmethod
    def new(cls, job_id: str, source: str, title: str, now: datetime | None = None) -> Self:
        instant = now or datetime.now(UTC)
        return cls(
            id=job_id,
            source=source,
            title=title,
            status=JobStatus.QUEUED,
            stage=None,
            progress=0.0,
            message="等待处理",
            error=None,
            created_at=instant,
            updated_at=instant,
            sentence_count=0,
        )

    def transition(self, target: JobStatus, now: datetime, **changes: Unpack[JobChanges]) -> Self:
        # 终态没有后继；所有调用方共享这一张状态转换表。
        allowed = {
            JobStatus.QUEUED: {JobStatus.RUNNING, JobStatus.FAILED},
            JobStatus.RUNNING: {JobStatus.SUCCEEDED, JobStatus.FAILED},
            JobStatus.SUCCEEDED: set(),
            JobStatus.FAILED: set(),
        }
        if target not in allowed[self.status]:
            raise ValueError(f"invalid job transition: {self.status} -> {target}")
        return replace(self, status=target, updated_at=now, **changes)


@dataclass(frozen=True, slots=True)
class JobQuery:
    status: JobStatus | None = None
    limit: int = 50
    cursor: str | None = None

    def __post_init__(self) -> None:
        if self.limit < 1:
            raise ValueError("limit must be positive")


@dataclass(frozen=True, slots=True)
class JobPage:
    items: tuple[Job, ...]
    next_cursor: str | None


@dataclass(frozen=True, slots=True)
class JobResult:
    job_id: str
    title: str
    source_url: str | None
    uploader: str | None
    thumbnail_url: str | None
    duration: float
    language: str | None
    transcript_source: str
    audio_artifact: str
    created_at: datetime
    sentences: tuple[Sentence, ...] = field(default_factory=tuple)
    has_clips: bool = False

    @property
    def sentence_count(self) -> int:
        return len(self.sentences)


@dataclass(frozen=True, slots=True)
class MediaInfo:
    path: Path
    title: str
    uploader: str | None
    source_url: str | None
    thumbnail_url: str | None
    subtitle_paths: tuple[Path, ...] = field(default_factory=tuple)
