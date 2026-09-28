import json
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from looplish_api.domain.models import (
    Job,
    JobOptions,
    JobPage,
    JobQuery,
    JobResult,
    JobStage,
    JobStatus,
    Problem,
    SegmentationOptions,
    Sentence,
    SubtitleSource,
    Word,
)
from looplish_api.domain.ports import ArtifactStore, JobRepository
from looplish_api.infrastructure.storage.file_artifact_store import FileArtifactStore
from looplish_api.infrastructure.storage.json_job_repository import JsonJobRepository
from looplish_api.infrastructure.storage.path_safety import ensure_within
from looplish_api.infrastructure.storage.serde import (
    job_from_dict,
    job_result_from_dict,
    job_result_to_dict,
    job_to_dict,
)

NOW = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
JOB_ID = "01JABCDEF123"


def full_job() -> Job:
    options = JobOptions(
        asr_backend="openai",
        asr_model="whisper-1",
        language="en",
        subtitle_source=SubtitleSource.EXISTING,
        subtitle_languages=("en", "en-US"),
        make_clips=True,
        segmentation=SegmentationOptions(max_duration=20.0, min_words=3),
    )
    return Job(
        id=JOB_ID,
        source="https://example.com/video",
        title="标题 with ümlaut",
        status=JobStatus.FAILED,
        stage=JobStage.TRANSCRIBING,
        progress=0.42,
        message="处理失败",
        error=Problem("ASR_FAILED", "识别失败。"),
        created_at=NOW,
        updated_at=NOW + timedelta(minutes=3),
        sentence_count=7,
        options=options,
    )


def full_result() -> JobResult:
    sentences = (
        Sentence(
            index=0,
            start=0.0,
            end=1.8,
            speech_start=0.2,
            speech_end=1.4,
            text="Hello world",
            words=(Word(0.2, 0.6, "Hello", 0.93), Word(0.7, 1.4, "world", None)),
        ),
        Sentence(1, 2.0, 3.5, 2.1, 3.1, "Second", ()),
    )
    return JobResult(
        job_id=JOB_ID,
        title="title",
        source_url="https://example.com/video",
        uploader="uploader",
        thumbnail_url="https://example.com/thumb.jpg",
        duration=12.5,
        language="en",
        transcript_source="asr",
        audio_artifact="audio.m4a",
        created_at=NOW,
        sentences=sentences,
        has_clips=True,
    )


def link_directory(link: Path, target: Path) -> None:
    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError:
        if os.name != "nt":
            raise
        # 无开发者模式的 Windows 不能建符号链接；目录联接同样会被 resolve() 解析。
        import _winapi

        _winapi.CreateJunction(str(target), str(link))


def test_rejects_path_escape(tmp_path: Path) -> None:
    store = FileArtifactStore(tmp_path)
    with pytest.raises(ValueError, match="invalid job id"):
        store.job_dir("../outside")


@pytest.mark.parametrize(
    "job_id",
    ["01jabcdef123", "01JABCDEF12", "0" * 27, "01JABCDEF12/", "01JABCDEF12.", ""],
)
def test_rejects_malformed_job_ids(tmp_path: Path, job_id: str) -> None:
    with pytest.raises(ValueError, match="invalid job id"):
        FileArtifactStore(tmp_path).job_dir(job_id)


def test_accepts_boundary_length_job_ids(tmp_path: Path) -> None:
    store = FileArtifactStore(tmp_path)

    assert store.job_dir("A" * 12) == tmp_path.resolve() / ("A" * 12)
    assert store.job_dir("Z9" * 13) == tmp_path.resolve() / ("Z9" * 13)


def test_rejects_unknown_artifact_names(tmp_path: Path) -> None:
    store = FileArtifactStore(tmp_path)

    for name in ("../job.json", "other.json", "source"):
        with pytest.raises(ValueError, match="unknown artifact name"):
            store.artifact_path(JOB_ID, name)


def test_ensure_within_rejects_root_and_prefix_sibling(tmp_path: Path) -> None:
    root = tmp_path / "jobs"

    with pytest.raises(ValueError, match="escapes"):
        ensure_within(root, root)
    # 字符串前缀相同的兄弟目录不是 root 的子目录。
    with pytest.raises(ValueError, match="escapes"):
        ensure_within(root, tmp_path / "jobs-other" / JOB_ID)
    with pytest.raises(ValueError, match="escapes"):
        ensure_within(root, root / ".." / "outside")
    assert ensure_within(root, root / JOB_ID) == root.resolve() / JOB_ID


def test_path_accessors_do_not_create_directories(tmp_path: Path) -> None:
    store = FileArtifactStore(tmp_path)

    store.job_dir(JOB_ID)
    store.artifact_path(JOB_ID, "result.json")

    assert not (tmp_path / JOB_ID).exists()
    assert store.read_result(JOB_ID) is None
    assert not (tmp_path / JOB_ID).exists()


def test_source_and_clips_dirs_are_created_inside_job(tmp_path: Path) -> None:
    store = FileArtifactStore(tmp_path)

    source = store.source_dir(JOB_ID)
    clips = store.clips_dir(JOB_ID)

    assert source == tmp_path.resolve() / JOB_ID / "source"
    assert clips == tmp_path.resolve() / JOB_ID / "clips"
    assert source.is_dir()
    assert clips.is_dir()


def test_job_serde_round_trips_all_fields() -> None:
    job = full_job()
    payload = job_to_dict(job)

    assert payload["createdAt"] == "2026-01-01T12:00:00Z"
    assert payload["options"]["segmentation"]["minWords"] == 3
    assert job_from_dict(json.loads(json.dumps(payload))) == job


def test_job_serde_round_trips_empty_optionals() -> None:
    job = Job.new(JOB_ID, "upload.mp4", "title", NOW)
    payload = job_to_dict(job)

    assert payload["stage"] is None
    assert payload["error"] is None
    assert payload["options"] is None
    assert job_from_dict(json.loads(json.dumps(payload))) == job


def test_job_from_dict_accepts_legacy_payload_without_options() -> None:
    payload = job_to_dict(Job.new(JOB_ID, "source", "title", NOW))
    del payload["options"]

    assert job_from_dict(payload).options is None


def test_job_result_round_trips_and_persists_sentence_count(tmp_path: Path) -> None:
    store = FileArtifactStore(tmp_path)
    result = full_result()

    store.write_result(JOB_ID, result)
    persisted = json.loads((tmp_path / JOB_ID / "result.json").read_text(encoding="utf-8"))

    assert persisted["sentenceCount"] == len(persisted["sentences"]) == 2
    assert persisted["sentences"][0]["duration"] == pytest.approx(1.8)
    assert store.read_result(JOB_ID) == result


def test_job_result_round_trips_empty_optionals() -> None:
    result = JobResult(
        job_id=JOB_ID,
        title="title",
        source_url=None,
        uploader=None,
        thumbnail_url=None,
        duration=3.0,
        language=None,
        transcript_source="subtitles",
        audio_artifact="audio.m4a",
        created_at=NOW,
    )

    restored = job_result_from_dict(json.loads(json.dumps(job_result_to_dict(result))))

    assert restored == result
    assert restored.sentence_count == 0


def test_repository_round_trips_job(tmp_path: Path) -> None:
    repository = JsonJobRepository(FileArtifactStore(tmp_path))
    job = Job.new("01JABCDEF123", "source", "title", datetime.now(UTC))
    repository.save(job)
    assert repository.get(job.id) == job
    assert not list(tmp_path.rglob("*.tmp"))


def test_repeated_save_keeps_valid_json_without_temp_files(tmp_path: Path) -> None:
    repository = JsonJobRepository(FileArtifactStore(tmp_path))
    job = full_job()

    repository.save(job)
    repository.save(job)

    json.loads((tmp_path / JOB_ID / "job.json").read_text(encoding="utf-8"))
    assert repository.get(JOB_ID) == job
    assert not list(tmp_path.rglob("*.tmp"))


def test_failed_write_keeps_original_file_and_cleans_temp(tmp_path: Path) -> None:
    store = FileArtifactStore(tmp_path)
    target = store.artifact_path(JOB_ID, "job.json")
    store.atomic_json(target, {"version": 1})

    with pytest.raises(TypeError):
        store.atomic_json(target, {"version": 2, "bad": object()})

    assert json.loads(target.read_text(encoding="utf-8")) == {"version": 1}
    assert not list(tmp_path.rglob("*.tmp"))


def test_atomic_json_rejects_paths_outside_root(tmp_path: Path) -> None:
    store = FileArtifactStore(tmp_path / "jobs")

    with pytest.raises(ValueError, match="escapes"):
        store.atomic_json(tmp_path / "outside.json", {})
    assert not (tmp_path / "outside.json").exists()


def test_get_unknown_job_does_not_create_directory(tmp_path: Path) -> None:
    repository = JsonJobRepository(FileArtifactStore(tmp_path))

    assert repository.get("01JUNKNOWN000") is None
    assert repository.delete("01JUNKNOWN000") is False
    assert not (tmp_path / "01JUNKNOWN000").exists()


def test_delete_removes_job_directory(tmp_path: Path) -> None:
    store = FileArtifactStore(tmp_path)
    repository = JsonJobRepository(store)
    repository.save(Job.new(JOB_ID, "source", "title", NOW))
    (store.source_dir(JOB_ID) / "media.mp4").write_bytes(b"data")

    assert repository.delete(JOB_ID) is True
    assert not (tmp_path / JOB_ID).exists()
    assert tmp_path.exists()


def test_delete_refuses_symlink_to_sibling_of_root(tmp_path: Path) -> None:
    root = tmp_path / "jobs"
    sibling = tmp_path / "jobs-other" / JOB_ID
    sibling.mkdir(parents=True)
    (sibling / "keep.txt").write_text("keep", encoding="utf-8")
    root.mkdir()
    link_directory(root / JOB_ID, sibling)

    with pytest.raises(ValueError, match="escapes"):
        FileArtifactStore(root).delete_job_dir(JOB_ID)
    assert (sibling / "keep.txt").exists()


def test_list_orders_newest_first_and_pages_with_cursor(tmp_path: Path) -> None:
    repository = JsonJobRepository(FileArtifactStore(tmp_path))
    ids = [f"01JOB{index:08d}" for index in range(5)]
    for offset, job_id in enumerate(ids):
        repository.save(Job.new(job_id, "source", "title", NOW + timedelta(seconds=offset)))

    first = repository.list(JobQuery(limit=2))
    second = repository.list(JobQuery(limit=2, cursor=first.next_cursor))
    last = repository.list(JobQuery(limit=2, cursor=second.next_cursor))

    assert [job.id for job in first.items] == ids[::-1][:2]
    assert [job.id for job in second.items] == ids[::-1][2:4]
    assert [job.id for job in last.items] == ids[::-1][4:]
    assert last.next_cursor is None


def test_list_uses_id_as_tiebreaker_and_filters_status(tmp_path: Path) -> None:
    repository = JsonJobRepository(FileArtifactStore(tmp_path))
    queued = Job.new("01JOBAAAAAAAA", "source", "title", NOW)
    running = Job.new("01JOBBBBBBBBB", "source", "title", NOW).transition(JobStatus.RUNNING, NOW)
    repository.save(queued)
    repository.save(running)

    assert [job.id for job in repository.list(JobQuery()).items] == [running.id, queued.id]
    assert repository.list(JobQuery(status=JobStatus.QUEUED)).items == (queued,)


def test_list_with_unknown_cursor_returns_empty_page(tmp_path: Path) -> None:
    repository = JsonJobRepository(FileArtifactStore(tmp_path))
    repository.save(Job.new(JOB_ID, "source", "title", NOW))

    assert repository.list(JobQuery(cursor="01JMISSING000")) == JobPage((), None)


def test_recover_interrupted_marks_job_failed(tmp_path: Path) -> None:
    repository = JsonJobRepository(FileArtifactStore(tmp_path))
    now = datetime.now(UTC)
    running = Job.new("01JABCDEF123", "source", "title", now).transition(JobStatus.RUNNING, now)
    repository.save(running)
    assert repository.recover_interrupted() == 1
    recovered = repository.get(running.id)
    assert recovered is not None
    assert recovered.status is JobStatus.FAILED
    assert recovered.error is not None
    assert recovered.error.code == "JOB_INTERRUPTED"


def test_recover_interrupted_spans_all_pages_and_skips_terminal_jobs(tmp_path: Path) -> None:
    repository = JsonJobRepository(FileArtifactStore(tmp_path))
    active_ids: list[str] = []
    for index in range(201):
        job = Job.new(f"01JOB{index:08d}", "source", "title", NOW + timedelta(seconds=index))
        if index % 2:
            job = job.transition(JobStatus.RUNNING, NOW, stage=JobStage.TRANSCRIBING)
        repository.save(job)
        active_ids.append(job.id)
    done = (
        Job.new("01JDONE000000", "source", "title", NOW)
        .transition(JobStatus.RUNNING, NOW)
        .transition(JobStatus.SUCCEEDED, NOW, sentence_count=4)
    )
    repository.save(done)

    assert repository.recover_interrupted() == 201

    for job_id in active_ids:
        recovered = repository.get(job_id)
        assert recovered is not None
        assert recovered.status is JobStatus.FAILED
        assert recovered.stage is None
        assert recovered.error == Problem("JOB_INTERRUPTED", "服务重启导致任务中断。")
    assert repository.get(done.id) == done
    assert repository.recover_interrupted() == 0


def test_concurrent_saves_leave_valid_json(tmp_path: Path) -> None:
    repository = JsonJobRepository(FileArtifactStore(tmp_path))
    base = Job.new(JOB_ID, "source", "title", NOW)

    def save(step: int) -> None:
        repository.save(base.transition(JobStatus.RUNNING, NOW, progress=step / 100))

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(save, range(100)))
        readers = [pool.submit(repository.get, JOB_ID) for _ in range(20)]

    for reader in readers:
        assert reader.result() is not None
    stored = json.loads((tmp_path / JOB_ID / "job.json").read_text(encoding="utf-8"))
    assert stored["status"] == "running"
    assert 0 <= stored["progress"] < 1
    assert not list(tmp_path.rglob("*.tmp"))


def test_atomic_write_uses_temp_file_in_target_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = FileArtifactStore(tmp_path)
    target = store.artifact_path(JOB_ID, "job.json")
    replaced: list[tuple[Path, Path]] = []
    real_replace = os.replace

    def spy(source: str, destination: Path) -> None:
        replaced.append((Path(source), Path(destination)))
        real_replace(source, destination)

    monkeypatch.setattr(os, "replace", spy)
    store.atomic_json(target, {"ok": True})

    [(source, destination)] = replaced
    assert source.parent == destination.parent == target.parent
    assert source.name.startswith(".job.json.")


def test_implementations_satisfy_domain_ports(tmp_path: Path) -> None:
    store: ArtifactStore = FileArtifactStore(tmp_path)
    repository: JobRepository = JsonJobRepository(FileArtifactStore(tmp_path))

    assert store.job_dir(JOB_ID).name == JOB_ID
    assert repository.list(JobQuery()) == JobPage((), None)
