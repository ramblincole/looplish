import logging
import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from looplish_api.application.job_runner import JobRunner
from looplish_api.domain.errors import ProcessingFailure, QueueFull, ServiceStopping
from looplish_api.domain.models import Job, JobResult, JobStatus, Sentence, Word
from looplish_api.infrastructure.storage.file_artifact_store import FileArtifactStore
from looplish_api.infrastructure.storage.json_job_repository import JsonJobRepository


def job_id(number: int) -> str:
    return f"{number:016X}"


def result(job: str, sentences: int = 2) -> JobResult:
    items = tuple(
        Sentence(index, index * 2.0, index * 2.0 + 1.5, index * 2.0 + 0.1, index * 2.0 + 1.0, "Hi.",
                 (Word(index * 2.0 + 0.1, index * 2.0 + 1.0, " Hi."),))
        for index in range(sentences)
    )  # fmt: skip
    return JobResult(
        job_id=job,
        title="t",
        source_url=None,
        uploader=None,
        thumbnail_url=None,
        duration=10.0,
        language="en",
        transcript_source="asr:test",
        audio_artifact="audio.m4a",
        created_at=datetime.now(UTC),
        sentences=items,
    )


class FakePipeline:
    def __init__(self, repository: JsonJobRepository) -> None:
        self.repository = repository
        self.behaviour: Callable[[str], JobResult] = result
        self.seen_status: dict[str, JobStatus] = {}
        self.started = threading.Event()
        self.release = threading.Event()
        self.release.set()

    def run(self, job: str) -> JobResult:
        current = self.repository.get(job)
        assert current is not None
        self.seen_status[job] = current.status
        self.started.set()
        self.release.wait(timeout=10)
        return self.behaviour(job)


@pytest.fixture
def repository(tmp_path: Path) -> JsonJobRepository:
    return JsonJobRepository(FileArtifactStore(tmp_path))


@pytest.fixture
def pipeline(repository: JsonJobRepository) -> FakePipeline:
    return FakePipeline(repository)


@pytest.fixture
def runners() -> Iterator[list[JobRunner]]:
    created: list[JobRunner] = []
    yield created
    for runner in created:
        runner.pipeline.release.set()  # type: ignore[attr-defined]
        runner.shutdown(grace_seconds=5)


def make_runner(
    pipeline: FakePipeline, runners: list[JobRunner], workers: int = 1, queue_size: int = 32
) -> JobRunner:
    runner = JobRunner(pipeline, max_workers=workers, queue_size=queue_size)  # type: ignore[arg-type]
    runners.append(runner)
    return runner


def enqueue(repository: JsonJobRepository, runner: JobRunner, number: int) -> str:
    identifier = job_id(number)
    repository.save(Job.new(identifier, "source", "title"))
    runner.submit(identifier)
    return identifier


def wait_for(repository: JsonJobRepository, identifier: str, status: JobStatus) -> Job:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        job = repository.get(identifier)
        if job is not None and job.status is status:
            return job
        time.sleep(0.01)
    raise AssertionError(f"{identifier} never reached {status}: {repository.get(identifier)}")


def test_job_runs_through_running_to_succeeded(
    repository: JsonJobRepository, pipeline: FakePipeline, runners: list[JobRunner]
) -> None:
    runner = make_runner(pipeline, runners)
    runner.start()

    identifier = enqueue(repository, runner, 1)
    done = wait_for(repository, identifier, JobStatus.SUCCEEDED)

    assert pipeline.seen_status[identifier] is JobStatus.RUNNING
    assert (done.progress, done.stage, done.sentence_count, done.error) == (1.0, None, 2, None)
    assert done.message == "处理完成"


def test_domain_failure_keeps_stable_code_and_detail(
    repository: JsonJobRepository, pipeline: FakePipeline, runners: list[JobRunner]
) -> None:
    def fail(job: str) -> JobResult:
        raise ProcessingFailure("SUBTITLE_NOT_AVAILABLE", "没有可用的人工字幕。")

    pipeline.behaviour = fail
    runner = make_runner(pipeline, runners)
    runner.start()

    failed = wait_for(repository, enqueue(repository, runner, 1), JobStatus.FAILED)

    assert failed.error is not None
    assert (failed.error.code, failed.error.detail) == (
        "SUBTITLE_NOT_AVAILABLE",
        "没有可用的人工字幕。",
    )
    assert failed.stage is None


def test_unknown_failure_is_generic_even_with_code_attribute(
    repository: JsonJobRepository, pipeline: FakePipeline, runners: list[JobRunner]
) -> None:
    class HttpError(Exception):
        code = 500
        detail = "secret internal path C:/Users/me/token.txt"

    def fail(job: str) -> JobResult:
        raise HttpError("boom")

    pipeline.behaviour = fail
    runner = make_runner(pipeline, runners)
    runner.start()

    failed = wait_for(repository, enqueue(repository, runner, 1), JobStatus.FAILED)

    assert failed.error is not None
    assert (failed.error.code, failed.error.detail) == ("INTERNAL_ERROR", "任务处理失败。")


def test_failed_job_keeps_last_recorded_progress(
    repository: JsonJobRepository, pipeline: FakePipeline, runners: list[JobRunner]
) -> None:
    def fail_midway(job: str) -> JobResult:
        current = repository.get(job)
        assert current is not None
        repository.save(replace(current, progress=0.4))
        raise ProcessingFailure("TRANSCRIPTION_FAILED", "x", 502)

    pipeline.behaviour = fail_midway
    runner = make_runner(pipeline, runners)
    runner.start()

    failed = wait_for(repository, enqueue(repository, runner, 1), JobStatus.FAILED)

    assert failed.progress == 0.4


def test_crashing_worker_is_logged_and_releases_its_slot(
    repository: JsonJobRepository,
    pipeline: FakePipeline,
    runners: list[JobRunner],
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    runner = make_runner(pipeline, runners)
    real_save = repository.save
    broken = job_id(1)

    def save(job: Job) -> None:
        if job.id == broken and job.status is JobStatus.RUNNING:
            raise OSError("disk full")
        real_save(job)

    monkeypatch.setattr(repository, "save", save)
    runner.start()

    with caplog.at_level(logging.ERROR):
        enqueue(repository, runner, 1)
        # 第一个任务在保存 running 时崩溃，槽位释放后第二个任务照常完成。
        wait_for(repository, enqueue(repository, runner, 2), JobStatus.SUCCEEDED)

    assert any(getattr(record, "event", None) == "job.worker_crashed" for record in caplog.records)


def test_deleted_or_already_finished_jobs_are_skipped(
    repository: JsonJobRepository, pipeline: FakePipeline, runners: list[JobRunner]
) -> None:
    runner = make_runner(pipeline, runners)
    runner.start()
    runner.submit(job_id(9))
    finished = Job.new(job_id(8), "s", "t").transition(JobStatus.FAILED, datetime.now(UTC))
    repository.save(finished)
    runner.submit(finished.id)

    wait_for(repository, enqueue(repository, runner, 1), JobStatus.SUCCEEDED)

    assert set(pipeline.seen_status) == {job_id(1)}
    assert repository.get(finished.id) == finished


def test_queue_is_bounded_while_workers_are_busy(
    repository: JsonJobRepository, pipeline: FakePipeline, runners: list[JobRunner]
) -> None:
    pipeline.release.clear()
    runner = make_runner(pipeline, runners, workers=1, queue_size=2)
    runner.start()

    first = enqueue(repository, runner, 1)
    assert pipeline.started.wait(5)
    wait_for(repository, first, JobStatus.RUNNING)
    time.sleep(0.3)  # 让调度线程有机会（错误地）多取一个任务
    enqueue(repository, runner, 2)
    enqueue(repository, runner, 3)

    with pytest.raises(QueueFull):
        enqueue(repository, runner, 4)

    pipeline.release.set()
    for number in (1, 2, 3):
        wait_for(repository, job_id(number), JobStatus.SUCCEEDED)


def test_parallel_workers_respect_max_workers(
    repository: JsonJobRepository, pipeline: FakePipeline, runners: list[JobRunner]
) -> None:
    active = 0
    peak = 0
    lock = threading.Lock()

    def slow(job: str) -> JobResult:
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        time.sleep(0.05)
        with lock:
            active -= 1
        return result(job)

    pipeline.behaviour = slow
    runner = make_runner(pipeline, runners, workers=2)
    runner.start()

    identifiers = [enqueue(repository, runner, number) for number in range(6)]
    for identifier in identifiers:
        wait_for(repository, identifier, JobStatus.SUCCEEDED)

    assert peak == 2


def test_shutdown_interrupts_waiting_jobs_and_lets_running_job_finish(
    repository: JsonJobRepository, pipeline: FakePipeline, runners: list[JobRunner]
) -> None:
    pipeline.release.clear()
    runner = make_runner(pipeline, runners)
    runner.start()
    running = enqueue(repository, runner, 1)
    assert pipeline.started.wait(5)
    waiting = [enqueue(repository, runner, number) for number in (2, 3)]

    stopper = threading.Thread(target=runner.shutdown, kwargs={"grace_seconds": 10})
    stopper.start()
    for identifier in waiting:
        interrupted = wait_for(repository, identifier, JobStatus.FAILED)
        assert interrupted.error is not None
        assert interrupted.error.code == "JOB_INTERRUPTED"
    # 已开始的任务不会被预先标记失败。
    running_job = repository.get(running)
    assert running_job is not None and running_job.status is JobStatus.RUNNING

    pipeline.release.set()
    stopper.join(timeout=10)

    assert not stopper.is_alive()
    assert wait_for(repository, running, JobStatus.SUCCEEDED).sentence_count == 2
    with pytest.raises(ServiceStopping):
        runner.submit(job_id(4))


def test_shutdown_with_full_queue_does_not_block(
    repository: JsonJobRepository, pipeline: FakePipeline, runners: list[JobRunner]
) -> None:
    pipeline.release.clear()
    runner = make_runner(pipeline, runners, queue_size=1)
    runner.start()
    enqueue(repository, runner, 1)
    assert pipeline.started.wait(5)
    enqueue(repository, runner, 2)

    began = time.monotonic()
    stopper = threading.Thread(target=runner.shutdown, kwargs={"grace_seconds": 0.2})
    stopper.start()
    stopper.join(timeout=5)

    assert not stopper.is_alive()
    assert time.monotonic() - began < 3
    pipeline.release.set()


def test_shutdown_before_start_is_safe(
    repository: JsonJobRepository, pipeline: FakePipeline, runners: list[JobRunner]
) -> None:
    runner = make_runner(pipeline, runners)
    pending = enqueue(repository, runner, 1)

    runner.shutdown(grace_seconds=1)

    failed = wait_for(repository, pending, JobStatus.FAILED)
    assert failed.error is not None and failed.error.code == "JOB_INTERRUPTED"


def test_concurrent_submit_and_shutdown_leave_no_job_queued(
    repository: JsonJobRepository, pipeline: FakePipeline, runners: list[JobRunner]
) -> None:
    runner = make_runner(pipeline, runners, workers=2, queue_size=200)
    runner.start()
    accepted: list[str] = []
    lock = threading.Lock()

    def producer(offset: int) -> None:
        for number in range(offset, offset + 40):
            identifier = job_id(number)
            repository.save(Job.new(identifier, "s", "t"))
            try:
                runner.submit(identifier)
            except ServiceStopping:
                repository.delete(identifier)
                continue
            with lock:
                accepted.append(identifier)

    producers = [threading.Thread(target=producer, args=(offset,)) for offset in (0, 100, 200)]
    for thread in producers:
        thread.start()
    time.sleep(0.02)
    runner.shutdown(grace_seconds=10)
    for thread in producers:
        thread.join()

    # 每个被接受的任务要么跑完，要么被标为中断，不会永远停在 queued。
    for identifier in accepted:
        job = repository.get(identifier)
        assert job is not None
        assert job.status in {JobStatus.SUCCEEDED, JobStatus.FAILED}, identifier
