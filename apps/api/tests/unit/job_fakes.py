"""流水线、执行器和任务服务测试共用的离线替身。"""

from collections.abc import Callable
from dataclasses import dataclass, field, replace
from pathlib import Path

from looplish_api.application.exporter import ArtifactExporter
from looplish_api.application.processing_pipeline import ProcessingPipeline
from looplish_api.domain.models import (
    Job,
    JobOptions,
    JobStage,
    MediaInfo,
    SegmentationOptions,
    SubtitleSource,
    Transcript,
    Word,
)
from looplish_api.domain.ports import ProgressCallback
from looplish_api.infrastructure.storage.file_artifact_store import FileArtifactStore
from looplish_api.infrastructure.storage.json_job_repository import JsonJobRepository

SENTENCE_ONE = " Listen to the story."
SENTENCE_TWO = " Then repeat it slowly."
VTT = (
    "WEBVTT\n\n"
    "00:00:01.000 --> 00:00:03.000\nSubtitle line one.\n\n"
    "00:00:04.000 --> 00:00:06.000\nSubtitle line two.\n"
)


def options(**changes: object) -> JobOptions:
    base = JobOptions(
        asr_backend="local",
        asr_model="small.en",
        language="en",
        subtitle_source=SubtitleSource.AUTO,
        subtitle_languages=("en",),
        make_clips=False,
        segmentation=SegmentationOptions(),
    )
    return replace(base, **changes)  # type: ignore[arg-type]


def transcript(duration: float = 8.0) -> Transcript:
    words = (
        Word(0.5, 0.9, " Listen"),
        Word(1.0, 1.2, " to"),
        Word(1.3, 1.5, " the"),
        Word(1.6, 2.2, " story."),
        Word(3.0, 3.4, " Then"),
        Word(3.5, 3.9, " repeat"),
        Word(4.0, 4.2, " it"),
        Word(4.3, 5.0, " slowly."),
    )
    return Transcript(words, "en", duration, "asr:recording:test")


@dataclass
class Calls:
    log: list[str] = field(default_factory=list)


class FakeDownloader:
    def __init__(self, calls: Calls, subtitles: dict[str, str] | None = None) -> None:
        self.calls = calls
        self.subtitles = subtitles or {}

    def download(
        self,
        url: str,
        workdir: Path,
        subtitle_languages: tuple[str, ...],
        progress: ProgressCallback | None = None,
    ) -> MediaInfo:
        self.calls.log.append("download")
        if progress is not None:
            progress(0.0, "解析视频信息")
            progress(0.5, "下载音频 50%")
        path = workdir / "source.webm"
        path.write_bytes(b"media")
        paths = []
        for name, content in self.subtitles.items():
            (workdir / name).write_text(content, encoding="utf-8")
            paths.append(workdir / name)
        return MediaInfo(
            path=path,
            title="Downloaded talk",
            uploader="Speaker",
            source_url=url,
            thumbnail_url="https://example.test/t.jpg",
            subtitle_paths=tuple(paths),
        )


class FakeMedia:
    def __init__(self, calls: Calls, duration: float = 8.0) -> None:
        self.calls = calls
        self.duration = duration
        self.asr_inputs: list[Path] = []

    def probe_duration(self, source: Path) -> float:
        self.calls.log.append("probe")
        return self.duration

    def _write(self, name: str, target: Path) -> Path:
        self.calls.log.append(name)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(name.encode())
        return target

    def to_web_audio(self, source: Path, target: Path) -> Path:
        return self._write("web_audio", target)

    def to_asr_wav(self, source: Path, target: Path) -> Path:
        self.asr_inputs.append(target)
        return self._write("asr_wav", target)

    def to_asr_mp3(self, source: Path, target: Path) -> Path:
        self.asr_inputs.append(target)
        return self._write("asr_mp3", target)

    def slice_asr_mp3(self, source: Path, target: Path, start: float, duration: float) -> Path:
        return self._write("slice_asr_mp3", target)

    def slice_audio(self, source: Path, target: Path, start: float, duration: float) -> Path:
        return self._write("slice_audio", target)


class RecordingBackend:
    def __init__(
        self,
        calls: Calls,
        name: str = "local",
        result: Transcript | None = None,
        error: Exception | None = None,
    ) -> None:
        self.calls = calls
        self.name = name
        self.result = result or transcript()
        self.error = error
        self.inputs: list[tuple[Path, bool]] = []

    def transcribe(
        self, audio_path: Path, language: str | None, progress: ProgressCallback | None
    ) -> Transcript:
        self.calls.log.append(f"transcribe:{self.name}")
        self.inputs.append((audio_path, audio_path.exists()))
        if progress is not None:
            progress(0.5, "识别中")
            progress(1.0, "识别完成")
        if self.error is not None:
            raise self.error
        return self.result


@dataclass
class Harness:
    root: Path
    calls: Calls
    store: FileArtifactStore
    repository: JsonJobRepository
    media: FakeMedia
    downloader: FakeDownloader
    backends: dict[str, RecordingBackend]
    progress: list[tuple[str, JobStage, float, str]]
    pipeline: ProcessingPipeline

    def save(self, job: Job) -> Job:
        self.repository.save(job)
        return job


def harness(
    root: Path,
    subtitles: dict[str, str] | None = None,
    asr_result: Transcript | None = None,
    asr_error: Exception | None = None,
    duration: float = 8.0,
    progress: Callable[[str, JobStage, float, str], None] | None = None,
) -> Harness:
    calls = Calls()
    store = FileArtifactStore(root / "jobs")
    repository = JsonJobRepository(store)
    media = FakeMedia(calls, duration)
    downloader = FakeDownloader(calls, subtitles)
    recorded: list[tuple[str, JobStage, float, str]] = []
    chosen = {
        name: RecordingBackend(calls, name, asr_result, asr_error) for name in ("local", "openai")
    }

    def sink(job_id: str, stage: JobStage, value: float, message: str) -> None:
        recorded.append((job_id, stage, value, message))
        if progress is not None:
            progress(job_id, stage, value, message)

    pipeline = ProcessingPipeline(
        repository,
        store,
        downloader,
        media,
        dict(chosen),  # type: ignore[arg-type]
        ArtifactExporter(store, media),
        sink,
    )
    return Harness(root, calls, store, repository, media, downloader, chosen, recorded, pipeline)
