import io
import json
import os
import subprocess
import sys
import zipfile
from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from looplish_api.api.dependencies import Container, build_container
from looplish_api.app_factory import create_app
from looplish_api.application.exporter import ArtifactExporter
from looplish_api.application.job_runner import JobRunner
from looplish_api.application.job_service import JobService
from looplish_api.application.processing_pipeline import ProcessingPipeline
from looplish_api.application.progress import ThrottledProgressSink
from looplish_api.config import Settings
from looplish_api.domain.models import (
    Job,
    JobResult,
    JobStatus,
    SegmentationOptions,
    Sentence,
    Word,
)
from looplish_api.infrastructure.asr.fake_backend import FakeTranscriptionBackend
from looplish_api.infrastructure.storage.file_artifact_store import FileArtifactStore
from looplish_api.infrastructure.storage.json_job_repository import JsonJobRepository

BASE_URL = "http://127.0.0.1:8756"
WEB_ORIGIN = "http://127.0.0.1:5173"
JOB_ID = "0123456789ABCDEF"
AUDIO = bytes(range(256)) * 4


class FakeMedia:
    """产物端点只需要切片；不启动 FFmpeg。"""

    def __init__(self) -> None:
        self.slices: list[tuple[float, float]] = []

    def probe_duration(self, source: Path) -> float:
        return 10.0

    def _write(self, target: Path) -> Path:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"mp3")
        return target

    def to_web_audio(self, source: Path, target: Path) -> Path:
        return self._write(target)

    def to_asr_wav(self, source: Path, target: Path) -> Path:
        return self._write(target)

    def to_asr_mp3(self, source: Path, target: Path) -> Path:
        return self._write(target)

    def slice_asr_mp3(self, source: Path, target: Path, start: float, duration: float) -> Path:
        return self._write(target)

    def slice_audio(self, source: Path, target: Path, start: float, duration: float) -> Path:
        self.slices.append((start, duration))
        return self._write(target)


class NoDownloads:
    def download(self, *args: object) -> Any:
        raise AssertionError("tests never download")


def settings(tmp_path: Path, **values: Any) -> Settings:
    base: dict[str, Any] = {
        "_env_file": None,
        "asr_backend": "fake",
        "data_dir": tmp_path / "jobs",
        "models_dir": tmp_path / "models",
        "log_dir": tmp_path / "logs",
        "ffmpeg_path": sys.executable,
        "ffprobe_path": sys.executable,
        "max_upload_bytes": 2048,
        "web_origin": WEB_ORIGIN,
    }
    base.update(values)
    return Settings(**base)


def make_container(config: Settings, media: FakeMedia | None = None) -> Container:
    store = FileArtifactStore(config.data_dir)
    repository = JsonJobRepository(store)
    media = media or FakeMedia()
    exporter = ArtifactExporter(store, media)
    pipeline = ProcessingPipeline(
        repository,
        store,
        NoDownloads(),
        media,
        {"fake": FakeTranscriptionBackend()},
        exporter,
        ThrottledProgressSink(repository),
    )
    runner = JobRunner(pipeline)
    service = JobService(
        repository,
        store,
        runner,
        exporter,
        config.max_upload_bytes,
        allow_local_paths=config.local_paths_enabled,
    )
    return Container(config, service, runner, store, repository, media, exporter)


@pytest.fixture
def container(tmp_path: Path) -> Container:
    return make_container(settings(tmp_path))


@pytest.fixture
def app(container: Container) -> FastAPI:
    return create_app(container)


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    # 不进入 lifespan：执行器不启动，创建的任务停在 queued，便于逐个端点断言。
    yield TestClient(app, base_url=BASE_URL)


def problem(response: Any, status: int, code: str) -> dict[str, Any]:
    assert response.status_code == status, response.text
    assert response.headers["content-type"].startswith("application/problem+json")
    body: dict[str, Any] = response.json()
    assert body["code"] == code
    assert body["status"] == status
    assert body["requestId"] == response.headers["X-Request-Id"]
    return body


def result(title: str = "Everyday Talk") -> JobResult:
    sentences = (
        Sentence(0, 0.3, 2.6, 0.5, 2.2, "Listen to the story.", (Word(0.5, 2.2, " Listen"),)),
        Sentence(1, 2.6, 5.4, 3.0, 5.0, "Then repeat it.", (Word(3.0, 5.0, " Then"),)),
    )
    return JobResult(
        job_id=JOB_ID,
        title=title,
        source_url="https://example.test/watch",
        uploader="Speaker",
        thumbnail_url=None,
        duration=6.0,
        language="en",
        transcript_source="asr:fake:fixture",
        audio_artifact="audio.m4a",
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        sentences=sentences,
    )


def succeeded(container: Container, title: str = "Everyday Talk") -> Job:
    job = replace(
        Job.new(JOB_ID, "https://example.test/watch", title),
        options=container.settings.default_job_options(),
    )
    job = job.transition(JobStatus.RUNNING, job.created_at).transition(
        JobStatus.SUCCEEDED, job.created_at, sentence_count=2
    )
    container.repository.save(job)
    value = result(title)
    container.store.artifact_path(JOB_ID, "audio.m4a").write_bytes(AUDIO)
    container.store.write_result(JOB_ID, value)
    container.exporter.write_text_artifacts(value)
    return job


# ---------------------------------------------------------------- 错误格式与 request ID


def test_unknown_job_returns_problem(client: TestClient) -> None:
    response = client.get("/api/v1/jobs/01JABCDEF123")

    problem(response, 404, "JOB_NOT_FOUND")


def test_unknown_route_is_a_problem_not_a_page(client: TestClient) -> None:
    problem(client.get("/api/v1/nothing-here"), 404, "NOT_FOUND")
    problem(client.put("/api/v1/jobs"), 405, "METHOD_NOT_ALLOWED")


def test_client_request_id_is_echoed(client: TestClient) -> None:
    response = client.get("/api/v1/jobs/01JABCDEF123", headers={"X-Request-Id": "trace-42"})

    assert response.headers["X-Request-Id"] == "trace-42"
    assert response.json()["requestId"] == "trace-42"


@pytest.mark.parametrize("supplied", ["x" * 129, "has space", "semi;colon", ""])
def test_unsafe_request_ids_are_replaced(client: TestClient, supplied: str) -> None:
    response = client.get("/api/v1/config", headers={"X-Request-Id": supplied})

    assert response.headers["X-Request-Id"] != supplied
    assert response.headers["X-Request-Id"].startswith("req_")


def test_validation_errors_are_problems_without_echoing_input(client: TestClient) -> None:
    body = problem(
        client.post(
            "/api/v1/jobs", json={"source": "https://x.test", "minDuration": "secret-value"}
        ),
        422,
        "VALIDATION_ERROR",
    )

    assert "minDuration" in body["detail"]
    assert "secret-value" not in body["detail"]


def test_unexpected_errors_hide_internals(
    container: Container, monkeypatch: pytest.MonkeyPatch
) -> None:
    def explode(*args: object) -> None:
        raise RuntimeError(f"boom at {container.settings.data_dir}")

    monkeypatch.setattr(container.service, "list_jobs", explode)
    client = TestClient(create_app(container), base_url=BASE_URL, raise_server_exceptions=False)

    body = problem(client.get("/api/v1/jobs"), 500, "INTERNAL_ERROR")

    assert str(container.settings.data_dir) not in json.dumps(body)
    assert "boom" not in json.dumps(body)


# ---------------------------------------------------------------- 配置与健康检查


def test_config_does_not_expose_secrets(client: TestClient) -> None:
    body = client.get("/api/v1/config").json()
    serialized = str(body).lower()

    assert "key" not in serialized
    assert "data_dir" not in serialized
    assert body["asrBackends"] == ["fake"]
    assert body["allowLocalPaths"] is True
    assert body["defaults"] == {
        "asrBackend": "fake",
        "asrModel": "small.en",
        "language": "en",
        "subtitleSource": "auto",
        "minDuration": 1.0,
        "maxDuration": 14.0,
        "hardPause": 0.75,
        "leadPad": 0.2,
        "tailPad": 0.4,
    }


def test_cloud_config_lists_only_configured_backend(tmp_path: Path) -> None:
    config = settings(tmp_path, asr_backend="groq", asr_api_key="sk-test-secret-value")
    client = TestClient(create_app(make_container(config)), base_url=BASE_URL)

    body = client.get("/api/v1/config").json()

    assert body["asrBackends"] == ["groq"]
    assert "sk-test-secret-value" not in json.dumps(body)


def test_live_and_ready(client: TestClient, container: Container) -> None:
    assert client.get("/health/live").json() == {"status": "ok"}
    assert client.get("/health/ready").json() == {"status": "ok"}
    assert container.settings.log_dir.is_dir()


def test_ready_reports_failed_components_without_paths(tmp_path: Path) -> None:
    config = settings(tmp_path, ffmpeg_path=str(tmp_path / "missing-ffmpeg"))
    client = TestClient(create_app(make_container(config)), base_url=BASE_URL)

    response = client.get("/health/ready")

    assert response.status_code == 503
    assert response.json() == {"status": "unavailable", "failed": ["ffmpeg"]}
    assert str(tmp_path) not in response.text


def test_ready_checks_local_asr_dependency(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "faster_whisper", None)
    import importlib.util

    monkeypatch.setattr(importlib.util, "find_spec", lambda name, *args: None)
    config = settings(tmp_path, asr_backend="local")
    client = TestClient(create_app(make_container(config)), base_url=BASE_URL)

    assert client.get("/health/ready").json()["failed"] == ["asrBackend"]


# ---------------------------------------------------------------- 创建任务


def test_create_url_job_uses_configured_defaults(client: TestClient, container: Container) -> None:
    response = client.post(
        "/api/v1/jobs", json={"source": "https://example.test/v", "maxDuration": 10}
    )

    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "queued"
    assert body["source"] == body["title"] == "https://example.test/v"
    assert body["progress"] == 0 and body["stage"] is None and body["error"] is None
    stored = container.repository.get(body["id"])
    assert stored is not None and stored.options is not None
    assert stored.options.language == "en"
    assert stored.options.segmentation == SegmentationOptions(max_duration=10)


@pytest.mark.parametrize("language", ["", "auto"])
def test_empty_or_auto_language_means_detection(
    client: TestClient, container: Container, language: str
) -> None:
    body = client.post(
        "/api/v1/jobs", json={"source": "https://example.test/v", "language": language}
    ).json()

    stored = container.repository.get(body["id"])
    assert stored is not None and stored.options is not None
    assert stored.options.language is None


def test_unconfigured_backend_is_rejected(client: TestClient) -> None:
    problem(
        client.post("/api/v1/jobs", json={"source": "https://x.test", "asrBackend": "openai"}),
        422,
        "INVALID_JOB_OPTIONS",
    )


@pytest.mark.parametrize(
    "payload",
    [
        {"source": "https://x.test", "minDuration": 5, "maxDuration": 5},
        {"source": "https://x.test", "hardPause": 9},
        {"source": "https://x.test", "unexpected": True},
        {"source": ""},
        {},
    ],
)
def test_invalid_create_requests_are_rejected(client: TestClient, payload: dict[str, Any]) -> None:
    problem(client.post("/api/v1/jobs", json=payload), 422, "VALIDATION_ERROR")


def test_partial_segmentation_conflicting_with_defaults_is_422(tmp_path: Path) -> None:
    config = settings(tmp_path, seg_min_seconds=3.0)
    client = TestClient(create_app(make_container(config)), base_url=BASE_URL)

    problem(
        client.post("/api/v1/jobs", json={"source": "https://x.test", "maxDuration": 2.5}),
        422,
        "INVALID_JOB_OPTIONS",
    )


def test_create_requires_json_body(client: TestClient) -> None:
    # 非 JSON 的「简单请求」无法创建任务，跨站表单拿不到这个入口。
    response = client.post(
        "/api/v1/jobs",
        content=json.dumps({"source": "https://x.test"}),
        headers={"Content-Type": "text/plain"},
    )

    problem(response, 422, "VALIDATION_ERROR")


def test_local_path_job_hides_absolute_path(client: TestClient, tmp_path: Path) -> None:
    media = tmp_path / "lesson.mp4"
    media.write_bytes(b"media")

    body = client.post("/api/v1/jobs", json={"source": str(media)}).json()

    assert body["source"] == body["title"] == "lesson.mp4"
    assert str(tmp_path) not in json.dumps(body)


@pytest.mark.parametrize("host", ["0.0.0.0", "192.168.1.10", "::"])
def test_local_paths_are_disabled_when_serving_beyond_loopback(tmp_path: Path, host: str) -> None:
    media = tmp_path / "lesson.mp4"
    media.write_bytes(b"media")
    config = settings(tmp_path, host=host)
    client = TestClient(create_app(make_container(config)), base_url=BASE_URL)

    assert client.get("/api/v1/config").json()["allowLocalPaths"] is False
    for source in (str(media), str(tmp_path / "missing.mp4")):
        # 存在与否都返回同一个错误，不泄露服务器上的文件信息。
        problem(client.post("/api/v1/jobs", json={"source": source}), 403, "LOCAL_PATHS_DISABLED")
    assert client.post("/api/v1/jobs", json={"source": "https://x.test/v"}).status_code == 202


@pytest.mark.parametrize(
    ("host", "explicit", "expected"),
    [("0.0.0.0", True, True), ("127.0.0.1", False, False), ("localhost", None, True)],
)
def test_local_path_switch_can_be_set_explicitly(
    tmp_path: Path, host: str, explicit: bool | None, expected: bool
) -> None:
    config = settings(tmp_path, host=host, allow_local_paths=explicit)
    client = TestClient(create_app(make_container(config)), base_url=BASE_URL)

    assert client.get("/api/v1/config").json()["allowLocalPaths"] is expected


def test_queue_full_maps_to_503(container: Container, monkeypatch: pytest.MonkeyPatch) -> None:
    runner = JobRunner(container.runner.pipeline, queue_size=1)
    monkeypatch.setattr(container.service, "runner", runner)
    client = TestClient(create_app(container), base_url=BASE_URL)

    assert client.post("/api/v1/jobs", json={"source": "https://x.test/1"}).status_code == 202
    problem(client.post("/api/v1/jobs", json={"source": "https://x.test/2"}), 503, "QUEUE_FULL")


# ---------------------------------------------------------------- 上传


def test_upload_small_file(client: TestClient, container: Container) -> None:
    response = client.post(
        "/api/v1/jobs/upload",
        files={"file": ("My Talk.wav", b"x" * 1000, "audio/wav")},
        data={"language": "auto", "makeClips": "true", "maxDuration": "10"},
    )

    assert response.status_code == 202, response.text
    body = response.json()
    assert body["title"] == body["source"] == "My Talk.wav"
    stored = container.repository.get(body["id"])
    assert stored is not None and stored.options is not None
    assert Path(stored.source).read_bytes() == b"x" * 1000
    assert stored.options.language is None
    assert stored.options.make_clips is True
    assert stored.options.segmentation.max_duration == 10


def test_upload_rejects_oversize_and_removes_temporary_file(
    client: TestClient, container: Container
) -> None:
    response = client.post(
        "/api/v1/jobs/upload",
        files={"file": ("large.wav", b"x" * 2049, "audio/wav")},
    )

    problem(response, 413, "UPLOAD_TOO_LARGE")
    assert not list(container.settings.data_dir.rglob("*.upload"))
    assert list(container.settings.data_dir.iterdir()) == []


def test_clearly_oversized_upload_is_rejected_before_parsing(
    client: TestClient, container: Container
) -> None:
    response = client.post(
        "/api/v1/jobs/upload",
        files={"file": ("huge.wav", b"x" * (1_048_576 + 4096), "audio/wav")},
    )

    problem(response, 413, "UPLOAD_TOO_LARGE")
    assert list(container.settings.data_dir.iterdir()) == []


def test_upload_reads_in_one_mib_chunks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from starlette.datastructures import UploadFile

    sizes: list[int] = []
    real_read = UploadFile.read

    async def recording_read(self: UploadFile, size: int = -1) -> bytes:
        sizes.append(size)
        return await real_read(self, size)

    monkeypatch.setattr(UploadFile, "read", recording_read)
    config = settings(tmp_path, max_upload_bytes=5 * 1_048_576)
    client = TestClient(create_app(make_container(config)), base_url=BASE_URL)

    response = client.post(
        "/api/v1/jobs/upload", files={"file": ("a.wav", b"y" * (2 * 1_048_576 + 5), "audio/wav")}
    )

    assert response.status_code == 202
    assert sizes and set(sizes) == {1_048_576}


@pytest.mark.parametrize(
    ("data", "code"),
    [
        ({"asrBackend": "openai"}, "INVALID_JOB_OPTIONS"),
        ({"minDuration": "0"}, "VALIDATION_ERROR"),
        ({"subtitleSource": "maybe"}, "VALIDATION_ERROR"),
    ],
)
def test_upload_options_share_json_validation(
    client: TestClient, container: Container, data: dict[str, str], code: str
) -> None:
    response = client.post(
        "/api/v1/jobs/upload", files={"file": ("a.wav", b"x", "audio/wav")}, data=data
    )

    problem(response, 422, code)
    assert list(container.settings.data_dir.iterdir()) == []


def test_upload_requires_file(client: TestClient) -> None:
    problem(client.post("/api/v1/jobs/upload", data={"language": "en"}), 422, "VALIDATION_ERROR")


# ---------------------------------------------------------------- 查询、删除、结果


def test_list_filters_and_pages(client: TestClient) -> None:
    ids = [
        client.post("/api/v1/jobs", json={"source": f"https://x.test/{n}"}).json()["id"]
        for n in range(3)
    ]

    first = client.get("/api/v1/jobs", params={"limit": 2}).json()
    second = client.get("/api/v1/jobs", params={"limit": 2, "cursor": first["nextCursor"]}).json()

    assert len(first["items"]) == 2 and first["nextCursor"] is not None
    assert len(second["items"]) == 1 and second["nextCursor"] is None
    assert {item["id"] for item in first["items"] + second["items"]} == set(ids)
    assert client.get("/api/v1/jobs", params={"status": "succeeded"}).json()["items"] == []


@pytest.mark.parametrize("params", [{"limit": 0}, {"limit": 201}, {"status": "paused"}])
def test_list_rejects_invalid_query(client: TestClient, params: dict[str, Any]) -> None:
    problem(client.get("/api/v1/jobs", params=params), 422, "VALIDATION_ERROR")


def test_get_and_delete_job(client: TestClient, container: Container) -> None:
    succeeded(container)

    assert client.get(f"/api/v1/jobs/{JOB_ID}").json()["sentenceCount"] == 2
    response = client.delete(f"/api/v1/jobs/{JOB_ID}")

    assert response.status_code == 204
    problem(client.get(f"/api/v1/jobs/{JOB_ID}"), 404, "JOB_NOT_FOUND")
    problem(client.delete(f"/api/v1/jobs/{JOB_ID}"), 404, "JOB_NOT_FOUND")


def test_running_job_cannot_be_deleted(client: TestClient, container: Container) -> None:
    job = Job.new(JOB_ID, "https://x.test", "t")
    container.repository.save(job.transition(JobStatus.RUNNING, job.created_at))

    problem(client.delete(f"/api/v1/jobs/{JOB_ID}"), 409, "JOB_RUNNING")


def test_result_shape_hides_artifact_names(client: TestClient, container: Container) -> None:
    succeeded(container)

    body = client.get(f"/api/v1/jobs/{JOB_ID}/result").json()

    assert body["jobId"] == JOB_ID
    assert body["audioUrl"] == f"/api/v1/jobs/{JOB_ID}/audio"
    assert body["sentenceCount"] == len(body["sentences"]) == 2
    assert body["thumbnailUrl"] is None
    assert body["sentences"][0]["speechStart"] == 0.5
    assert body["sentences"][0]["words"][0] == {
        "start": 0.5,
        "end": 2.2,
        "text": " Listen",
        "probability": None,
    }
    assert "audio.m4a" not in json.dumps(body)


def test_result_of_unfinished_job_is_not_ready(client: TestClient) -> None:
    job_id = client.post("/api/v1/jobs", json={"source": "https://x.test"}).json()["id"]

    problem(client.get(f"/api/v1/jobs/{job_id}/result"), 409, "JOB_NOT_READY")
    problem(client.get(f"/api/v1/jobs/{job_id}/audio"), 409, "JOB_NOT_READY")


def test_resegment_merges_partial_parameters(client: TestClient, container: Container) -> None:
    succeeded(container)

    response = client.post(f"/api/v1/jobs/{JOB_ID}/resegment", json={"leadPad": 0, "tailPad": 0})

    assert response.status_code == 200, response.text
    sentences = response.json()["sentences"]
    assert all(item["start"] == item["speechStart"] for item in sentences)
    stored = container.repository.get(JOB_ID)
    assert stored is not None and stored.options is not None
    assert stored.options.segmentation == SegmentationOptions(lead_pad=0, tail_pad=0)


def test_resegment_requires_a_parameter(client: TestClient, container: Container) -> None:
    succeeded(container)

    problem(client.post(f"/api/v1/jobs/{JOB_ID}/resegment", json={}), 422, "VALIDATION_ERROR")
    problem(
        client.post(f"/api/v1/jobs/{JOB_ID}/resegment", json={"minDuration": 20}),
        422,
        "VALIDATION_ERROR",
    )


# ---------------------------------------------------------------- 媒体与下载


def test_audio_supports_range_requests(client: TestClient, container: Container) -> None:
    succeeded(container)

    full = client.get(f"/api/v1/jobs/{JOB_ID}/audio")
    partial = client.get(f"/api/v1/jobs/{JOB_ID}/audio", headers={"Range": "bytes=10-19"})

    assert full.status_code == 200 and full.content == AUDIO
    assert full.headers["content-type"] == "audio/mp4"
    assert full.headers["accept-ranges"] == "bytes"
    assert full.headers["content-disposition"].startswith("inline;")
    assert partial.status_code == 206
    assert partial.content == AUDIO[10:20]
    assert partial.headers["content-range"] == f"bytes 10-19/{len(AUDIO)}"


def test_missing_artifact_is_404_not_500(client: TestClient, container: Container) -> None:
    succeeded(container)
    container.store.artifact_path(JOB_ID, "audio.m4a").unlink()
    container.store.artifact_path(JOB_ID, "subtitles.vtt").unlink()

    problem(client.get(f"/api/v1/jobs/{JOB_ID}/audio"), 404, "ARTIFACT_NOT_FOUND")
    problem(client.get(f"/api/v1/jobs/{JOB_ID}/subtitles.vtt"), 404, "ARTIFACT_NOT_FOUND")


@pytest.mark.parametrize(
    ("fmt", "media_type", "marker"),
    [
        ("srt", "application/x-subrip", "00:00:00,500 --> 00:00:02,200"),
        ("vtt", "text/vtt", "WEBVTT"),
        ("txt", "text/plain", "Listen to the story.\n"),
    ],
)
def test_subtitle_downloads(
    client: TestClient, container: Container, fmt: str, media_type: str, marker: str
) -> None:
    succeeded(container, title='课程 "一" / Part:1')

    response = client.get(f"/api/v1/jobs/{JOB_ID}/subtitles.{fmt}")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith(media_type)
    assert marker in response.text
    disposition = response.headers["content-disposition"]
    assert disposition.startswith("attachment;")
    assert "/" not in disposition.split("filename*=")[0].split("filename=")[1]
    assert f"filename*=UTF-8''%E8%AF%BE%E7%A8%8B%20%E4%B8%80%20%20Part1.{fmt}" in disposition


def test_unknown_subtitle_format_is_rejected(client: TestClient, container: Container) -> None:
    succeeded(container)

    assert client.get(f"/api/v1/jobs/{JOB_ID}/subtitles.docx").status_code in {404, 422}


def test_clip_is_generated_on_demand_and_cached(client: TestClient, container: Container) -> None:
    succeeded(container)
    media = container.media
    assert isinstance(media, FakeMedia)

    first = client.get(f"/api/v1/jobs/{JOB_ID}/clips/1")
    second = client.get(f"/api/v1/jobs/{JOB_ID}/clips/1")

    assert first.status_code == second.status_code == 200
    assert first.headers["content-type"] == "audio/mpeg"
    assert media.slices == [(2.6, pytest.approx(2.8))]
    problem(client.get(f"/api/v1/jobs/{JOB_ID}/clips/2"), 404, "SENTENCE_NOT_FOUND")
    problem(client.get(f"/api/v1/jobs/{JOB_ID}/clips/-1"), 422, "VALIDATION_ERROR")


@pytest.mark.parametrize(("clips", "expected"), [("true", 2), ("false", 0)])
def test_bundle_download(
    client: TestClient, container: Container, clips: str, expected: int
) -> None:
    succeeded(container)

    response = client.get(f"/api/v1/jobs/{JOB_ID}/bundle.zip", params={"clips": clips})

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        names = archive.namelist()
    assert len([name for name in names if name.startswith("clips/")]) == expected
    assert "subtitles.srt" in names


# ---------------------------------------------------------------- CORS、来源与主机校验


def test_cors_allows_only_configured_origin(client: TestClient) -> None:
    allowed = client.options(
        "/api/v1/jobs",
        headers={"Origin": WEB_ORIGIN, "Access-Control-Request-Method": "POST"},
    )
    denied = client.options(
        "/api/v1/jobs",
        headers={"Origin": "https://evil.test", "Access-Control-Request-Method": "POST"},
    )

    assert allowed.headers.get("access-control-allow-origin") == WEB_ORIGIN
    assert "access-control-allow-origin" not in denied.headers
    assert (
        client.get("/api/v1/config", headers={"Origin": "https://evil.test"}).headers.get(
            "access-control-allow-origin"
        )
        is None
    )


@pytest.mark.parametrize(
    ("origin", "status"),
    [("https://evil.test", 403), (WEB_ORIGIN, 202), (BASE_URL, 202), (None, 202)],
)
def test_cross_site_writes_are_rejected(
    client: TestClient, origin: str | None, status: int
) -> None:
    headers = {"Origin": origin} if origin else {}

    response = client.post(
        "/api/v1/jobs/upload", files={"file": ("a.wav", b"x", "audio/wav")}, headers=headers
    )

    assert response.status_code == status
    if status == 403:
        problem(response, 403, "ORIGIN_NOT_ALLOWED")


def test_foreign_host_header_is_rejected_on_loopback(client: TestClient) -> None:
    problem(
        client.get("/api/v1/config", headers={"Host": "attacker.test:8756"}),
        403,
        "HOST_NOT_ALLOWED",
    )
    assert client.get("/api/v1/config", headers={"Host": "localhost:8756"}).status_code == 200


def test_host_is_not_restricted_when_serving_publicly(tmp_path: Path) -> None:
    client = TestClient(create_app(make_container(settings(tmp_path, host="0.0.0.0"))))

    assert client.get("/api/v1/config", headers={"Host": "looplish.example"}).status_code == 200


# ---------------------------------------------------------------- 静态站点


@pytest.fixture
def site(tmp_path: Path) -> TestClient:
    dist = tmp_path / "web"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html>app</html>", encoding="utf-8")
    (dist / "assets" / "app.js").write_text("console.log(1)", encoding="utf-8")
    (dist / "robots.txt").write_text("ok", encoding="utf-8")
    (tmp_path / "secret.txt").write_text("secret", encoding="utf-8")
    config = settings(tmp_path, web_dist_dir=dist)
    return TestClient(create_app(make_container(config)), base_url=BASE_URL)


def test_static_files_and_spa_fallback(site: TestClient) -> None:
    html = {"Accept": "text/html"}

    assert site.get("/", headers=html).text == "<html>app</html>"
    asset = site.get("/assets/app.js")
    assert asset.headers["cache-control"] == "public, max-age=31536000, immutable"
    assert site.get("/robots.txt").headers["cache-control"] == "no-cache"
    page = site.get("/library/123", headers=html)
    assert page.text == "<html>app</html>" and page.headers["cache-control"] == "no-cache"
    assert site.get("/missing.js").status_code == 404


@pytest.mark.parametrize("path", ["/api/v1/nope", "/health/nope", "/api", "/api/v1/jobs/X/audio"])
def test_spa_never_answers_api_or_health_paths(site: TestClient, path: str) -> None:
    response = site.get(path, headers={"Accept": "text/html"})

    assert response.status_code in {404, 422}
    assert "app" not in response.text
    assert response.headers["content-type"].startswith("application/problem+json")


def test_static_site_blocks_traversal(site: TestClient) -> None:
    response = site.get("/..%2Fsecret.txt", headers={"Accept": "*/*"})

    assert response.status_code == 404
    assert "secret" not in response.text


def test_missing_index_fails_at_startup(tmp_path: Path) -> None:
    (tmp_path / "web").mkdir()

    with pytest.raises(RuntimeError, match=r"index\.html"):
        create_app(make_container(settings(tmp_path, web_dist_dir=tmp_path / "web")))


# ---------------------------------------------------------------- 装配、生命周期与入口


def test_build_container_shares_one_instance_graph(tmp_path: Path) -> None:
    container = build_container(settings(tmp_path))

    assert container.service.runner is container.runner
    assert container.service.store is container.store
    assert container.service.repository is container.repository
    assert container.runner.pipeline.repository is container.repository
    assert container.runner.pipeline.media is container.media
    assert container.service.exporter is container.exporter
    assert container.service.allow_local_paths is True
    assert set(container.runner.pipeline.transcribers) == {"fake"}


def test_lifespan_recovers_then_starts_and_stops(container: Container) -> None:
    job = Job.new(JOB_ID, "https://x.test", "t")
    container.repository.save(job.transition(JobStatus.RUNNING, job.created_at))

    with TestClient(create_app(container), base_url=BASE_URL):
        recovered = container.repository.get(JOB_ID)
        assert recovered is not None and recovered.error is not None
        assert recovered.error.code == "JOB_INTERRUPTED"
        assert container.runner.dispatcher.is_alive()

    assert container.runner.stopping.is_set()


def test_openapi_lists_every_designed_endpoint(app: FastAPI) -> None:
    paths = app.openapi()["paths"]

    expected = {
        "/health/live": {"get"},
        "/health/ready": {"get"},
        "/api/v1/config": {"get"},
        "/api/v1/jobs": {"get", "post"},
        "/api/v1/jobs/upload": {"post"},
        "/api/v1/jobs/{job_id}": {"get", "delete"},
        "/api/v1/jobs/{job_id}/result": {"get"},
        "/api/v1/jobs/{job_id}/resegment": {"post"},
        "/api/v1/jobs/{job_id}/audio": {"get"},
        "/api/v1/jobs/{job_id}/subtitles.{fmt}": {"get"},
        "/api/v1/jobs/{job_id}/clips/{index}": {"get"},
        "/api/v1/jobs/{job_id}/bundle.zip": {"get"},
    }
    for path, methods in expected.items():
        assert methods <= set(paths[path]), path


def test_main_module_imports_with_process_environment(tmp_path: Path) -> None:
    env = {
        **{key: value for key, value in os.environ.items() if not key.startswith("LOOPLISH_")},
        "LOOPLISH_ENV_FILE": "",
        "LOOPLISH_ASR_BACKEND": "fake",
        "LOOPLISH_DATA_DIR": str(tmp_path / "jobs"),
        "LOOPLISH_MODELS_DIR": str(tmp_path / "models"),
        "LOOPLISH_LOG_DIR": str(tmp_path / "logs"),
    }
    script = "from looplish_api.main import app; print('/api/v1/jobs' in app.openapi()['paths'])"

    completed = subprocess.run(
        [sys.executable, "-c", script], env=env, capture_output=True, text=True, timeout=60
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "True"
    assert (tmp_path / "jobs").is_dir() and (tmp_path / "logs" / "looplish.jsonl").exists()


@pytest.mark.parametrize(
    ("origin", "status"),
    [
        # Vite 代理会把 Host 改写成 API 地址；用 localhost 打开前端时也必须能提交。
        ("http://localhost:5173", 202),
        ("http://[::1]:5173", 202),
        ("http://localhost:9999", 403),
        ("https://localhost:5173", 403),
    ],
)
def test_loopback_origin_spellings_are_equivalent(
    client: TestClient, origin: str, status: int
) -> None:
    response = client.post(
        "/api/v1/jobs", json={"source": "https://x.test/v"}, headers={"Origin": origin}
    )

    assert response.status_code == status


def test_loopback_equivalence_only_applies_to_a_loopback_web_origin(tmp_path: Path) -> None:
    config = settings(tmp_path, web_origin="https://looplish.example")
    client = TestClient(create_app(make_container(config)), base_url=BASE_URL)

    problem(
        client.post(
            "/api/v1/jobs",
            json={"source": "https://x.test/v"},
            headers={"Origin": "http://localhost:5173"},
        ),
        403,
        "ORIGIN_NOT_ALLOWED",
    )
    allowed = client.post(
        "/api/v1/jobs",
        json={"source": "https://x.test/v"},
        headers={"Origin": "https://looplish.example"},
    )
    assert allowed.status_code == 202
