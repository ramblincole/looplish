from dataclasses import replace
from pathlib import Path

import pytest
from job_fakes import VTT, Harness, harness, options, transcript

from looplish_api.application.progress import (
    ProgressReporter,
    StageWeight,
    ThrottledProgressSink,
    pipeline_stages,
)
from looplish_api.domain.errors import InvalidJobOptions, ProcessingFailure
from looplish_api.domain.models import Job, JobStage, JobStatus, SubtitleSource, Transcript, Word
from looplish_api.infrastructure.storage.file_artifact_store import FileArtifactStore
from looplish_api.infrastructure.storage.json_job_repository import JsonJobRepository

URL = "https://example.test/watch?v=1"
JOB_ID = "0123456789ABCDEF"


# ---------------------------------------------------------------- ProgressReporter


def collect() -> tuple[list[tuple[JobStage, float, str]], ProgressReporter]:
    seen: list[tuple[JobStage, float, str]] = []
    reporter = ProgressReporter(
        (
            StageWeight(JobStage.PREPARING_AUDIO, 1),
            StageWeight(JobStage.TRANSCRIBING, 3),
        ),
        lambda stage, value, message: seen.append((stage, value, message)),
    )
    return seen, reporter


@pytest.mark.parametrize(
    "stages",
    [(), (StageWeight(JobStage.SEGMENTING, 0),), (StageWeight(JobStage.SEGMENTING, -1),)],
    ids=["empty", "zero", "negative"],
)
def test_reporter_rejects_unusable_weights(stages: tuple[StageWeight, ...]) -> None:
    with pytest.raises(ValueError, match="positive weights"):
        ProgressReporter(stages, lambda *args: None)


def test_reporter_rejects_undeclared_stage() -> None:
    _, reporter = collect()

    with pytest.raises(ValueError, match="unknown progress stage"):
        reporter.report(JobStage.DOWNLOADING, 0.5, "x")


def test_reporter_normalizes_weights_across_stages() -> None:
    seen, reporter = collect()

    reporter.report(JobStage.PREPARING_AUDIO, 1.0, "a")
    reporter.report(JobStage.TRANSCRIBING, 0.5, "b")
    reporter.report(JobStage.TRANSCRIBING, 1.0, "c")

    assert [value for _, value, _ in seen] == pytest.approx([0.25, 0.625, 1.0])


def test_reporter_is_monotonic_and_clamps_local_values() -> None:
    seen, reporter = collect()

    reporter.report(JobStage.TRANSCRIBING, 0.5, "late")
    reporter.report(JobStage.PREPARING_AUDIO, 0.0, "earlier stage")
    reporter.report(JobStage.TRANSCRIBING, -3, "negative")
    reporter.report(JobStage.TRANSCRIBING, 7, "overflow")

    values = [value for _, value, _ in seen]
    assert values == sorted(values)
    assert values[-1] == 1.0


def test_download_stage_only_counts_for_url_jobs() -> None:
    assert pipeline_stages(True)[0].stage is JobStage.DOWNLOADING
    assert JobStage.DOWNLOADING not in [item.stage for item in pipeline_stages(False)]


# ---------------------------------------------------------------- 节流写盘


def running_job(repository: JsonJobRepository) -> Job:
    job = Job.new(JOB_ID, "source", "title").transition(
        JobStatus.RUNNING, Job.new(JOB_ID, "s", "t").created_at
    )
    repository.save(job)
    return job


def test_sink_throttles_same_stage_but_writes_stage_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository = JsonJobRepository(FileArtifactStore(tmp_path))
    running_job(repository)
    saves: list[float] = []
    real_save = repository.save
    monkeypatch.setattr(
        repository, "save", lambda job: (saves.append(job.progress), real_save(job))
    )
    now = [0]
    sink = ThrottledProgressSink(repository, interval_ns=200, clock=lambda: now[0])

    sink(JOB_ID, JobStage.TRANSCRIBING, 0.1, "a")
    now[0] = 100
    sink(JOB_ID, JobStage.TRANSCRIBING, 0.2, "b")
    now[0] = 150
    sink(JOB_ID, JobStage.SEGMENTING, 0.3, "c")
    now[0] = 200
    sink(JOB_ID, JobStage.SEGMENTING, 0.4, "d")
    now[0] = 350
    sink(JOB_ID, JobStage.SEGMENTING, 0.5, "e")

    assert saves == [0.1, 0.3, 0.5]
    stored = repository.get(JOB_ID)
    assert stored is not None
    assert (stored.stage, stored.progress, stored.message) == (JobStage.SEGMENTING, 0.5, "e")


def test_sink_never_touches_non_running_jobs(tmp_path: Path) -> None:
    repository = JsonJobRepository(FileArtifactStore(tmp_path))
    queued = Job.new(JOB_ID, "source", "title")
    repository.save(queued)

    ThrottledProgressSink(repository)(JOB_ID, JobStage.SEGMENTING, 0.9, "x")
    ThrottledProgressSink(repository)("FEDCBA9876543210", JobStage.SEGMENTING, 0.9, "x")

    assert repository.get(JOB_ID) == queued


# ---------------------------------------------------------------- 流水线主路径


def queued(h: Harness, source: str, **option_changes: object) -> Job:
    return h.save(replace(Job.new(JOB_ID, source, source), options=options(**option_changes)))


def test_url_with_subtitles_skips_asr(tmp_path: Path) -> None:
    h = harness(tmp_path, subtitles={"source.en.vtt": VTT})
    queued(h, URL)

    result = h.pipeline.run(JOB_ID)

    assert h.calls.log == ["download", "probe", "web_audio"]
    assert result.transcript_source == "subtitle:source.en.vtt"
    assert [sentence.text for sentence in result.sentences] == [
        "Subtitle line one.",
        "Subtitle line two.",
    ]
    assert (result.title, result.uploader, result.source_url) == ("Downloaded talk", "Speaker", URL)
    assert result.thumbnail_url == "https://example.test/t.jpg"
    assert h.store.read_result(JOB_ID) == result
    job_dir = h.store.job_dir(JOB_ID)
    for name in ("subtitles.srt", "subtitles.vtt", "sentences.txt", "anki_import.tsv"):
        assert (job_dir / name).is_file()


def test_url_with_asr_choice_ignores_available_subtitles(tmp_path: Path) -> None:
    h = harness(tmp_path, subtitles={"source.en.vtt": VTT})
    queued(h, URL, subtitle_source=SubtitleSource.ASR)

    result = h.pipeline.run(JOB_ID)

    assert h.calls.log == ["download", "probe", "web_audio", "asr_wav", "transcribe:local"]
    assert result.transcript_source == "asr:recording:test"
    assert [sentence.text for sentence in result.sentences] == [
        "Listen to the story.",
        "Then repeat it slowly.",
    ]


@pytest.mark.parametrize(
    ("backend", "converter", "artifact"),
    [("local", "asr_wav", "asr-input.wav"), ("openai", "asr_mp3", "asr-upload.mp3")],
)
def test_uploaded_file_uses_backend_specific_input_and_cleans_it(
    tmp_path: Path, backend: str, converter: str, artifact: str
) -> None:
    h = harness(tmp_path)
    upload = h.store.source_dir(JOB_ID) / "source-talk.mp4"
    upload.write_bytes(b"media")
    queued(h, str(upload), asr_backend=backend)

    h.pipeline.run(JOB_ID)

    assert h.calls.log == ["probe", "web_audio", converter, f"transcribe:{backend}"]
    [(path, existed)] = h.backends[backend].inputs
    assert path.name == artifact and existed
    assert not path.exists()


def test_asr_input_is_cleaned_after_failure(tmp_path: Path) -> None:
    h = harness(tmp_path, asr_error=ProcessingFailure("TRANSCRIPTION_FAILED", "x", 502))
    queued(h, URL, subtitle_source=SubtitleSource.ASR)

    with pytest.raises(ProcessingFailure, match="TRANSCRIPTION_FAILED"):
        h.pipeline.run(JOB_ID)

    assert h.media.asr_inputs
    assert not any(path.exists() for path in h.media.asr_inputs)


def test_existing_mode_without_subtitles_fails(tmp_path: Path) -> None:
    h = harness(tmp_path)
    queued(h, URL, subtitle_source=SubtitleSource.EXISTING)

    with pytest.raises(ProcessingFailure, match="SUBTITLE_NOT_AVAILABLE"):
        h.pipeline.run(JOB_ID)

    assert "transcribe:local" not in h.calls.log


def test_auto_mode_falls_back_to_asr_when_subtitle_is_unusable(tmp_path: Path) -> None:
    h = harness(tmp_path, subtitles={"source.en.vtt": "WEBVTT\n\n"})
    queued(h, URL)

    result = h.pipeline.run(JOB_ID)

    assert "transcribe:local" in h.calls.log
    assert result.transcript_source == "asr:recording:test"


def test_subtitle_language_priority_is_respected(tmp_path: Path) -> None:
    british = VTT.replace("Subtitle", "British")
    h = harness(tmp_path, subtitles={"source.en.vtt": VTT, "source.en-GB.vtt": british})
    queued(h, URL, subtitle_languages=("en-GB", "en"))

    result = h.pipeline.run(JOB_ID)

    assert result.transcript_source == "subtitle:source.en-GB.vtt"
    assert result.sentences[0].text.startswith("British")


def test_unconfigured_backend_is_rejected(tmp_path: Path) -> None:
    h = harness(tmp_path)
    queued(h, URL, subtitle_source=SubtitleSource.ASR, asr_backend="groq")

    with pytest.raises(InvalidJobOptions):
        h.pipeline.run(JOB_ID)


def test_make_clips_generates_every_clip(tmp_path: Path) -> None:
    h = harness(tmp_path)
    queued(h, URL, subtitle_source=SubtitleSource.ASR, make_clips=True)

    result = h.pipeline.run(JOB_ID)

    assert result.has_clips is True
    assert h.calls.log.count("slice_audio") == len(result.sentences) == 2
    assert sorted(path.name for path in h.store.clips_dir(JOB_ID).iterdir()) == [
        "000001.mp3",
        "000002.mp3",
    ]


def test_without_make_clips_no_clip_is_generated(tmp_path: Path) -> None:
    h = harness(tmp_path)
    queued(h, URL, subtitle_source=SubtitleSource.ASR)

    result = h.pipeline.run(JOB_ID)

    assert result.has_clips is False
    assert "slice_audio" not in h.calls.log


def test_progress_is_global_monotonic_and_ends_at_one(tmp_path: Path) -> None:
    h = harness(tmp_path)
    queued(h, URL, subtitle_source=SubtitleSource.ASR)

    h.pipeline.run(JOB_ID)

    values = [value for _, _, value, _ in h.progress]
    assert values == sorted(values)
    assert values[0] == 0.0
    assert values[-1] == pytest.approx(1.0)
    assert h.progress[0][1] is JobStage.DOWNLOADING
    # 下载器的细分进度按下载阶段转发，用户能看到每一步在做什么。
    messages = [(stage, message) for _, stage, _, message in h.progress]
    assert (JobStage.DOWNLOADING, "下载音频 50%") in messages
    assert (JobStage.PREPARING_AUDIO, "转换播放用音频") in messages
    assert (JobStage.TRANSCRIBING, "转换识别用音频") in messages


def test_upload_progress_starts_without_download_stage(tmp_path: Path) -> None:
    h = harness(tmp_path)
    upload = h.store.source_dir(JOB_ID) / "source-talk.mp4"
    upload.write_bytes(b"media")
    queued(h, str(upload))

    h.pipeline.run(JOB_ID)

    assert JobStage.DOWNLOADING not in {stage for _, stage, _, _ in h.progress}


def test_transcript_slightly_longer_than_probe_does_not_fail(tmp_path: Path) -> None:
    # 识别用的音频比原媒体多出几毫秒，末尾的词不能被判定越界。
    base = transcript(duration=8.02)
    words = (*base.words, Word(7.5, 8.015, " end."))
    h = harness(
        tmp_path,
        asr_result=Transcript(words, "en", 8.02, "asr:recording:test"),
        duration=8.0,
    )
    queued(h, URL, subtitle_source=SubtitleSource.ASR)

    result = h.pipeline.run(JOB_ID)

    assert result.duration == 8.02
    assert result.sentences[-1].speech_end == 8.015


def test_missing_job_or_options_is_rejected(tmp_path: Path) -> None:
    h = harness(tmp_path)

    with pytest.raises(ValueError, match="options are required"):
        h.pipeline.run(JOB_ID)
