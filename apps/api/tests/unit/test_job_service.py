import asyncio
import json
import logging
import re
import time
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from job_fakes import SENTENCE_ONE, harness, options

from looplish_api.application.commands import CreateJobCommand, ResegmentCommand, UploadJobCommand
from looplish_api.application.exporter import ArtifactExporter
from looplish_api.application.job_runner import JobRunner
from looplish_api.application.job_service import JobService, safe_upload_name
from looplish_api.application.progress import ThrottledProgressSink
from looplish_api.domain.errors import (
    JobNotFound,
    JobNotReady,
    JobRunning,
    QueueFull,
    ServiceStopping,
    SourceNotSupported,
    UploadTooLarge,
    WordsNotAvailable,
)
from looplish_api.domain.models import (
    Job,
    JobQuery,
    JobStatus,
    SegmentationOptions,
    SubtitleSource,
)
from looplish_api.logging import JsonFormatter, configure_logging

URL = "https://example.test/watch?v=1"
MIB = 1_048_576


class RecordingRunner:
    """只记录入队顺序的执行器替身；可模拟队列已满或正在停止。"""

    def __init__(self, service_repository: Any = None, error: Exception | None = None) -> None:
        self.submitted: list[tuple[str, JobStatus | None]] = []
        self.error = error
        self.repository = service_repository
        self.stopping = __import__("threading").Event()

    def submit(self, job_id: str) -> None:
        stored = self.repository.get(job_id) if self.repository is not None else None
        self.submitted.append((job_id, stored.status if stored is not None else None))
        if self.error is not None:
            raise self.error


def service(
    tmp_path: Path, runner: Any = None, max_upload: int = 10 * MIB
) -> tuple[JobService, Any]:
    h = harness(tmp_path)
    runner = runner or RecordingRunner()
    if isinstance(runner, RecordingRunner):
        runner.repository = h.repository
    return JobService(
        h.repository, h.store, runner, ArtifactExporter(h.store, h.media), max_upload
    ), h


# ---------------------------------------------------------------- 创建


def test_create_from_url_saves_queued_before_enqueue(tmp_path: Path) -> None:
    svc, h = service(tmp_path)

    job = svc.create_from_source(CreateJobCommand(URL, options()))

    assert re.fullmatch(r"[0-9A-F]{16}", job.id)
    assert (job.status, job.title, job.source) == (JobStatus.QUEUED, URL, URL)
    assert job.options == options()
    assert svc.runner.submitted == [(job.id, JobStatus.QUEUED)]
    assert h.repository.get(job.id) == job


def test_job_ids_are_unpredictable(tmp_path: Path) -> None:
    svc, _ = service(tmp_path)

    ids = {svc.create_from_source(CreateJobCommand(URL, options())).id for _ in range(20)}

    assert len(ids) == 20


def test_create_from_existing_local_file(tmp_path: Path) -> None:
    media = tmp_path / "lesson one.mp4"
    media.write_bytes(b"media")
    svc, _ = service(tmp_path / "data")

    job = svc.create_from_source(CreateJobCommand(f"  {media}  ", options()))

    assert job.source == str(media.resolve())
    assert job.title == "lesson one.mp4"


@pytest.mark.parametrize(
    "source", ["ftp://example.test/a.mp4", "relative/file.mp4", "C:/definitely/missing.mp4", ""]
)
def test_unsupported_sources_are_rejected_without_saving(tmp_path: Path, source: str) -> None:
    svc, h = service(tmp_path)

    with pytest.raises(SourceNotSupported):
        svc.create_from_source(CreateJobCommand(source, options()))

    assert h.repository.list(JobQuery()).items == ()


def test_directory_is_not_a_media_file(tmp_path: Path) -> None:
    svc, _ = service(tmp_path / "data")

    with pytest.raises(SourceNotSupported):
        svc.create_from_source(CreateJobCommand(str(tmp_path), options()))


def test_queue_full_persists_failed_job_and_raises(tmp_path: Path) -> None:
    svc, h = service(tmp_path, RecordingRunner(error=QueueFull()))

    with pytest.raises(QueueFull):
        svc.create_from_source(CreateJobCommand(URL, options()))

    [stored] = h.repository.list(JobQuery()).items
    assert stored.status is JobStatus.FAILED
    assert stored.error is not None and stored.error.code == "QUEUE_FULL"


def test_stopping_service_rejects_before_saving(tmp_path: Path) -> None:
    runner = RecordingRunner()
    runner.stopping.set()
    svc, h = service(tmp_path, runner)

    with pytest.raises(ServiceStopping):
        svc.create_from_source(CreateJobCommand(URL, options()))

    assert h.repository.list(JobQuery()).items == ()
    assert runner.submitted == []


# ---------------------------------------------------------------- 上传


class FakeUpload:
    def __init__(self, data: bytes, fail_after: int | None = None) -> None:
        self.data = data
        self.position = 0
        self.sizes: list[int] = []
        self.closed = False
        self.fail_after = fail_after

    async def read(self, size: int = -1) -> bytes:
        self.sizes.append(size)
        if self.fail_after is not None and self.position >= self.fail_after:
            raise ConnectionResetError("client went away")
        chunk = self.data[self.position : self.position + size]
        self.position += len(chunk)
        return chunk

    async def close(self) -> None:
        self.closed = True


def upload(svc: JobService, data: FakeUpload, filename: str = "Talk 1.mp4") -> Job:
    return asyncio.run(svc.create_from_upload(data, UploadJobCommand(filename, options())))


def test_upload_streams_in_one_mib_chunks(tmp_path: Path) -> None:
    svc, h = service(tmp_path)
    payload = bytes(range(256)) * (MIB * 2 // 256 + 17)
    stream = FakeUpload(payload)

    job = upload(svc, stream)

    assert set(stream.sizes) == {MIB}
    assert stream.closed
    path = Path(job.source)
    assert path.read_bytes() == payload
    assert path.parent == h.store.source_dir(job.id)
    assert path.name == "source-Talk_1.mp4"
    assert job.title == "Talk 1.mp4"
    assert svc.runner.submitted == [(job.id, JobStatus.QUEUED)]
    assert not list(tmp_path.rglob("*.upload"))


def test_oversized_upload_is_stopped_and_cleaned(tmp_path: Path) -> None:
    svc, h = service(tmp_path, max_upload=MIB + 10)
    stream = FakeUpload(b"x" * (3 * MIB))

    with pytest.raises(UploadTooLarge):
        upload(svc, stream)

    assert stream.closed
    # 超限后立即停止读取，不把剩余内容读完。
    assert len(stream.sizes) == 2
    assert not list(tmp_path.rglob("*.upload"))
    assert list((tmp_path / "jobs").iterdir()) == []
    assert h.repository.list(JobQuery()).items == ()


def test_interrupted_upload_is_cleaned(tmp_path: Path) -> None:
    svc, _ = service(tmp_path)
    stream = FakeUpload(b"x" * (3 * MIB), fail_after=MIB)

    with pytest.raises(ConnectionResetError):
        upload(svc, stream)

    assert stream.closed
    assert not list(tmp_path.rglob("*.upload"))
    assert list((tmp_path / "jobs").iterdir()) == []


def test_upload_rejected_while_stopping_still_closes_stream(tmp_path: Path) -> None:
    runner = RecordingRunner()
    runner.stopping.set()
    svc, _ = service(tmp_path, runner)
    stream = FakeUpload(b"data")

    with pytest.raises(ServiceStopping):
        upload(svc, stream)

    assert stream.closed
    assert list((tmp_path / "jobs").iterdir()) == []


@pytest.mark.parametrize(
    ("filename", "expected"),
    [
        ("../../etc/passwd", "source-passwd"),
        ("..", "source-upload"),
        ("", "source-upload"),
        (".hidden.mp3", "source-hidden.mp3"),
        ("C:\\Users\\me\\My Clip (1).mp4", "source-My_Clip__1_.mp4"),
        ("CON", "source-CON"),
        ("语音.mp3", "source-__.mp3"),
        ("_draft_.mp3", "source-_draft_.mp3"),
    ],
)
def test_upload_names_are_sanitized(filename: str, expected: str) -> None:
    assert safe_upload_name(filename) == expected


def test_long_upload_names_are_truncated_keeping_extension() -> None:
    assert safe_upload_name("a" * 300 + ".mp3") == "source-" + "a" * 96 + ".mp3"


# ---------------------------------------------------------------- 查询与删除


def succeeded_job(tmp_path: Path) -> tuple[JobService, Any, Job]:
    svc, h = service(tmp_path)
    job = replace(
        Job.new("0123456789ABCDEF", URL, URL), options=options(subtitle_source=SubtitleSource.ASR)
    )
    h.save(job)
    h.repository.save(job.transition(JobStatus.RUNNING, job.created_at))
    h.pipeline.run(job.id)
    running = h.repository.get(job.id)
    h.repository.save(running.transition(JobStatus.SUCCEEDED, job.created_at, sentence_count=2))
    return svc, h, h.repository.get(job.id)


def test_list_get_and_result(tmp_path: Path) -> None:
    svc, _, job = succeeded_job(tmp_path)

    assert svc.list_jobs(JobQuery()).items == (job,)
    assert svc.get_job(job.id) == job
    assert svc.get_result(job.id).sentence_count == 2


@pytest.mark.parametrize("identifier", ["FFFFFFFFFFFFFFFF", "../outside", "lower-case-id"])
def test_unknown_or_malformed_job_ids_are_not_found(tmp_path: Path, identifier: str) -> None:
    svc, _ = service(tmp_path)

    with pytest.raises(JobNotFound):
        svc.get_job(identifier)
    with pytest.raises(JobNotFound):
        svc.delete(identifier)


def test_result_requires_succeeded_job(tmp_path: Path) -> None:
    svc, _ = service(tmp_path)
    job = svc.create_from_source(CreateJobCommand(URL, options()))

    with pytest.raises(JobNotReady):
        svc.get_result(job.id)


def test_running_job_cannot_be_deleted(tmp_path: Path) -> None:
    svc, h = service(tmp_path)
    job = svc.create_from_source(CreateJobCommand(URL, options()))
    h.repository.save(job.transition(JobStatus.RUNNING, job.created_at))

    with pytest.raises(JobRunning):
        svc.delete(job.id)

    assert h.repository.get(job.id) is not None


def test_delete_removes_job_directory(tmp_path: Path) -> None:
    svc, h, job = succeeded_job(tmp_path)

    svc.delete(job.id)

    assert not h.store.job_dir(job.id).exists()
    with pytest.raises(JobNotFound):
        svc.get_job(job.id)


# ---------------------------------------------------------------- 重新切句


def test_resegment_reuses_persisted_words_without_processing(tmp_path: Path) -> None:
    svc, h, job = succeeded_job(tmp_path)
    exporter = svc.exporter
    before = svc.get_result(job.id)
    exporter.ensure_clip(before, 0)
    exporter.build_bundle(before, include_clips=False)
    h.calls.log.clear()
    transcribed = sum(len(backend.inputs) for backend in h.backends.values())
    tight = SegmentationOptions(lead_pad=0.0, tail_pad=0.0)

    updated = svc.resegment(job.id, ResegmentCommand(tight))

    # 不下载、不转码、不识别：媒体与识别后端在重切句期间没有任何调用。
    assert h.calls.log == []
    assert sum(len(backend.inputs) for backend in h.backends.values()) == transcribed
    words_before = [word for sentence in before.sentences for word in sentence.words]
    words_after = [word for sentence in updated.sentences for word in sentence.words]
    assert words_after == words_before
    # 新参数生效：没有留白时切片边界正好等于发声边界，而旧结果带留白。
    assert updated.sentences != before.sentences
    for sentence in updated.sentences:
        assert (sentence.start, sentence.end) == (sentence.speech_start, sentence.speech_end)
    assert updated.has_clips is False
    assert list(h.store.clips_dir(job.id).iterdir()) == []
    assert not h.store.artifact_path(job.id, "bundle.zip").exists()
    assert svc.get_result(job.id) == updated
    srt = h.store.artifact_path(job.id, "subtitles.srt").read_text(encoding="utf-8")
    assert srt.count("-->") == len(updated.sentences)
    stored = svc.get_job(job.id)
    assert stored.sentence_count == len(updated.sentences)
    assert stored.options is not None and stored.options.segmentation == tight
    assert stored.status is JobStatus.SUCCEEDED


def test_resegment_requires_finished_job(tmp_path: Path) -> None:
    svc, _ = service(tmp_path)
    job = svc.create_from_source(CreateJobCommand(URL, options()))

    with pytest.raises(JobNotReady):
        svc.resegment(job.id, ResegmentCommand(SegmentationOptions()))


def test_resegment_without_words_is_rejected(tmp_path: Path) -> None:
    svc, h, job = succeeded_job(tmp_path)
    empty = replace(svc.get_result(job.id), sentences=())
    h.store.write_result(job.id, empty)

    with pytest.raises(WordsNotAvailable):
        svc.resegment(job.id, ResegmentCommand(SegmentationOptions()))


# ---------------------------------------------------------------- 端到端与日志


def test_full_flow_through_runner_and_logs_stay_clean(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    secret = "sk-test-secret-value-123"
    h = harness(tmp_path)
    sink = ThrottledProgressSink(h.repository)
    h.pipeline.progress = sink
    runner = JobRunner(h.pipeline)
    svc = JobService(h.repository, h.store, runner, ArtifactExporter(h.store, h.media), 10 * MIB)
    runner.start()
    try:
        with caplog.at_level(logging.DEBUG):
            job = svc.create_from_source(
                CreateJobCommand(URL, options(subtitle_source=SubtitleSource.ASR))
            )
            deadline = time.monotonic() + 10
            while svc.get_job(job.id).status is not JobStatus.SUCCEEDED:
                assert time.monotonic() < deadline
                time.sleep(0.01)
    finally:
        runner.shutdown(grace_seconds=5)

    assert svc.get_result(job.id).sentence_count == 2
    events = [getattr(record, "event", None) for record in caplog.records]
    assert {"job.queued", "job.started", "job.succeeded"} <= set(events)
    for forbidden in (secret, str(tmp_path), SENTENCE_ONE.strip(), URL):
        assert forbidden not in caplog.text


def test_json_formatter_only_emits_whitelisted_fields() -> None:
    record = logging.LogRecord(
        "looplish", logging.INFO, __file__, 1, "path C:/Users/me secret sk-123", None, None
    )
    record.event = "job.failed"
    record.jobId = "0123456789ABCDEF"
    record.errorCode = "TRANSCRIPTION_FAILED"
    record.authorization = "Bearer sk-123"

    payload = json.loads(JsonFormatter().format(record))

    assert set(payload) == {"timestamp", "level", "event", "jobId", "errorCode"}
    assert payload["event"] == "job.failed"
    assert "sk-123" not in json.dumps(payload)


def test_configure_logging_writes_jsonl(tmp_path: Path) -> None:
    root = logging.getLogger()
    saved = (root.handlers[:], root.level)
    try:
        configure_logging(tmp_path / "logs")
        logging.getLogger("looplish.test").info("ignored text", extra={"event": "test.event"})
        for handler in root.handlers:
            handler.flush()
        lines = (tmp_path / "logs" / "looplish.jsonl").read_text(encoding="utf-8").splitlines()
    finally:
        for handler in root.handlers:
            handler.close()
        root.handlers[:], root.level = saved[0], saved[1]

    assert json.loads(lines[-1])["event"] == "test.event"
    assert "ignored text" not in lines[-1]


def test_disabled_local_paths_reject_without_touching_filesystem(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from looplish_api.domain.errors import LocalPathsDisabled

    svc, _ = service(tmp_path)
    svc.allow_local_paths = False
    media = tmp_path / "lesson.mp4"
    media.write_bytes(b"media")
    touched: list[object] = []
    monkeypatch.setattr(Path, "is_file", lambda self: touched.append(self) or True)

    for source in (str(media), str(tmp_path / "missing.mp4")):
        with pytest.raises(LocalPathsDisabled):
            svc.create_from_source(CreateJobCommand(source, options()))

    assert touched == []
    assert svc.create_from_source(CreateJobCommand(URL, options())).status is JobStatus.QUEUED


@pytest.mark.parametrize("operation", ["bundle", "clip"])
def test_artifacts_use_result_read_inside_the_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    # 模拟重切句恰好发生在「读取结果」与「生成产物」之间：取锁的瞬间完成一次重切句。
    svc, h, job = succeeded_job(tmp_path)
    fresh = SegmentationOptions(lead_pad=0.0, tail_pad=0.0)

    class ResegmentOnAcquire:
        def __init__(self, inner: Any) -> None:
            self.inner = inner
            self.fired = False

        def __enter__(self) -> None:
            self.inner.__enter__()
            if not self.fired:
                self.fired = True
                svc.resegment(job.id, ResegmentCommand(fresh))

        def __exit__(self, *args: object) -> None:
            self.inner.__exit__(*args)

    monkeypatch.setattr(svc, "_artifact_lock", ResegmentOnAcquire(svc._artifact_lock))

    if operation == "bundle":
        used, _ = svc.bundle_file(job.id, include_clips=True)
    else:
        used, _ = svc.clip_file(job.id, 0)

    latest = svc.get_result(job.id)
    assert used == latest
    assert all(item.start == item.speech_start for item in used.sentences)
    srt = h.store.artifact_path(job.id, "subtitles.srt").read_text(encoding="utf-8")
    assert srt.count("-->") == len(latest.sentences)


def test_clip_index_is_checked_against_latest_result(tmp_path: Path) -> None:
    svc, h, job = succeeded_job(tmp_path)
    current = svc.get_result(job.id)
    h.store.write_result(job.id, replace(current, sentences=current.sentences[:1]))

    from looplish_api.domain.errors import SentenceNotFound

    with pytest.raises(SentenceNotFound):
        svc.clip_file(job.id, 1)
