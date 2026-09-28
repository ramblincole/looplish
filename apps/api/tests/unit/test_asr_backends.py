import json
import logging
import sys
import threading
import traceback
import types
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
from openai import OpenAI

from looplish_api.config import Settings
from looplish_api.domain.errors import ProcessingFailure
from looplish_api.domain.models import JobResult, SegmentationOptions
from looplish_api.domain.segmentation import build_sentences
from looplish_api.infrastructure.asr.fake_backend import FakeTranscriptionBackend
from looplish_api.infrastructure.asr.local_backend import LocalWhisperBackend
from looplish_api.infrastructure.asr.openai_backend import (
    ChunkedCloudBackend,
    OpenAICompatibleBackend,
)
from looplish_api.infrastructure.asr.registry import GROQ_BASE_URL, build_backend
from looplish_api.infrastructure.asr.timeline import build_transcript
from looplish_api.infrastructure.storage.serde import job_result_to_dict

SECRET = "sk-test-secret-value-123"


def audio_file(tmp_path: Path, size: int = 5) -> Path:
    path = tmp_path / "input.mp3"
    with path.open("wb") as handle:
        # 稀疏文件：只设长度不写内容，51 MB 也不占实际磁盘。
        handle.truncate(size)
    return path


# ---------------------------------------------------------------- 假 SDK 客户端


class Response:
    def __init__(self, words: list[Any] | None, duration: float | None = 2.0) -> None:
        self.words = words
        self.duration = duration


class Client:
    def __init__(self, *responses: Any) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, Any]] = []
        self.audio = types.SimpleNamespace(
            transcriptions=types.SimpleNamespace(create=self._create)
        )

    def _create(self, **kwargs: Any) -> Any:
        kwargs["file_bytes"] = len(kwargs["file"].read())
        self.calls.append(kwargs)
        response = self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]
        if isinstance(response, Exception):
            raise response
        return response


def words(*items: tuple[float, float, str]) -> list[dict[str, Any]]:
    return [{"start": start, "end": end, "word": text} for start, end, text in items]


def test_cloud_backend_maps_words(tmp_path: Path) -> None:
    client = Client(Response(words((0.1, 0.5, " hello"))))
    backend = OpenAICompatibleBackend("openai", client, "whisper-1", 25_000_000)

    result = backend.transcribe(audio_file(tmp_path), "en", None)

    assert result.words[0].text == " hello"
    assert result.source == "asr:openai:whisper-1"
    assert result.language == "en"
    assert result.duration == 2.0


def test_cloud_backend_requests_word_level_verbose_json(tmp_path: Path) -> None:
    client = Client(Response(words((0.1, 0.5, "hi"))))

    OpenAICompatibleBackend("groq", client, "model-x", 25_000_000).transcribe(
        audio_file(tmp_path), None, None
    )

    [call] = client.calls
    assert call["model"] == "model-x"
    assert call["language"] is None
    assert call["response_format"] == "verbose_json"
    assert call["timestamp_granularities"] == ["word"]
    assert call["file_bytes"] == 5


@pytest.mark.parametrize("missing", [None, []])
def test_cloud_backend_rejects_missing_words(tmp_path: Path, missing: list[Any] | None) -> None:
    backend = OpenAICompatibleBackend("openai", Client(Response(missing)), "model", 25_000_000)

    with pytest.raises(ProcessingFailure, match="TRANSCRIPTION_FAILED") as exc:
        backend.transcribe(audio_file(tmp_path), "en", None)

    assert "词级时间戳" in exc.value.detail


def test_cloud_backend_rejects_segment_only_response(tmp_path: Path) -> None:
    backend = OpenAICompatibleBackend("openai", Client(object()), "model", 25_000_000)

    with pytest.raises(ProcessingFailure, match="TRANSCRIPTION_FAILED"):
        backend.transcribe(audio_file(tmp_path), "en", None)


def test_cloud_words_get_leading_space_so_sentences_do_not_glue(tmp_path: Path) -> None:
    # 云端返回的词不带前导空格，拼句子时不能变成 HelloWorld。
    client = Client(Response(words((0.1, 0.4, "Hello"), (0.5, 0.9, "world."))))
    transcript = OpenAICompatibleBackend("openai", client, "m", 25_000_000).transcribe(
        audio_file(tmp_path), "en", None
    )

    sentences = build_sentences(transcript.words, transcript.duration, SegmentationOptions())

    assert [word.text for word in transcript.words] == [" Hello", " world."]
    assert sentences[0].text == "Hello world."


def test_cloud_backend_accepts_sdk_objects_and_missing_duration(tmp_path: Path) -> None:
    item = types.SimpleNamespace(start=0.2, end=0.7, word=" yes")
    backend = OpenAICompatibleBackend("openai", Client(Response([item], None)), "m", 25_000_000)

    transcript = backend.transcribe(audio_file(tmp_path), "en", None)

    assert transcript.words[0].text == " yes"
    assert transcript.duration == pytest.approx(0.7)


def test_cloud_backend_rejects_oversized_file_without_uploading(tmp_path: Path) -> None:
    client = Client(Response(words((0.1, 0.5, "x"))))

    with pytest.raises(ProcessingFailure, match="单次上传限制"):
        OpenAICompatibleBackend("openai", client, "m", 4).transcribe(
            audio_file(tmp_path, 5), "en", None
        )

    assert client.calls == []


def test_cloud_backend_reports_progress(tmp_path: Path) -> None:
    seen: list[tuple[float, str]] = []
    backend = OpenAICompatibleBackend(
        "openai", Client(Response(words((0.1, 0.5, "x")))), "m", 25_000_000
    )

    backend.transcribe(audio_file(tmp_path), "en", lambda value, text: seen.append((value, text)))

    assert seen == [(1.0, "云端识别完成")]


# ---------------------------------------------------------------- 真实 SDK + 模拟 HTTP


def sdk_client(handler: Any) -> OpenAI:
    return OpenAI(
        api_key=SECRET,
        base_url="https://asr.test/v1",
        max_retries=0,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )


def test_real_sdk_request_and_response_round_trip(tmp_path: Path) -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(
            200,
            json={
                "text": "Hello, world.",
                "language": "english",
                "duration": 1.5,
                "words": words((0.0, 0.5, "Hello,"), (0.6, 1.2, "world.")),
                "segments": [],
            },
        )

    backend = OpenAICompatibleBackend("openai", sdk_client(handler), "whisper-1", 25_000_000)
    transcript = backend.transcribe(audio_file(tmp_path), "en", None)

    body = captured[0].read().decode("latin-1")
    assert 'name="response_format"\r\n\r\nverbose_json' in body
    assert 'name="timestamp_granularities[]"\r\n\r\nword' in body
    assert 'name="language"\r\n\r\nen' in body
    assert captured[0].url.path == "/v1/audio/transcriptions"
    assert [word.text for word in transcript.words] == [" Hello,", " world."]
    assert transcript.duration == 1.5


def test_provider_error_echoing_key_never_leaks(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        # 模拟供应商在错误正文里回显 Key。
        return httpx.Response(401, json={"error": {"message": f"Incorrect API key: {SECRET}"}})

    backend = OpenAICompatibleBackend("openai", sdk_client(handler), "whisper-1", 25_000_000)

    with caplog.at_level(logging.DEBUG), pytest.raises(ProcessingFailure) as exc:
        backend.transcribe(audio_file(tmp_path), "en", None)

    rendered = "".join(traceback.format_exception(exc.value))
    assert exc.value.code == "TRANSCRIPTION_FAILED"
    assert SECRET not in str(exc.value)
    assert SECRET not in rendered
    assert SECRET not in caplog.text
    assert "AuthenticationError (HTTP 401)" in caplog.text


# ---------------------------------------------------------------- 分块包装器


class FakeMediaProcessor:
    def __init__(self, duration: float = 300.0, chunk_bytes: int = 1000) -> None:
        self.duration = duration
        self.chunk_bytes = chunk_bytes
        self.slices: list[tuple[Path, float, float]] = []
        self.probed = 0

    def probe_duration(self, source: Path) -> float:
        self.probed += 1
        return self.duration

    def to_web_audio(self, source: Path, target: Path) -> Path:
        raise AssertionError("not used")

    def to_asr_wav(self, source: Path, target: Path) -> Path:
        raise AssertionError("not used")

    def to_asr_mp3(self, source: Path, target: Path) -> Path:
        raise AssertionError("not used")

    def slice_asr_mp3(self, source: Path, target: Path, start: float, duration: float) -> Path:
        self.slices.append((target, start, duration))
        target.write_bytes(b"x" * self.chunk_bytes)
        return target

    def slice_audio(self, source: Path, target: Path, start: float, duration: float) -> Path:
        raise AssertionError("cloud chunks must use the 32 kbps ASR slice")


def chunk_response(*items: tuple[float, float, str]) -> Response:
    return Response(words(*items), 100.0)


def chunked(client: Client, media: FakeMediaProcessor) -> ChunkedCloudBackend:
    delegate = OpenAICompatibleBackend("openai", client, "whisper-1", 25_000_000)
    return ChunkedCloudBackend(delegate, media, 24_000_000)


def leftover_chunk_dirs(tmp_path: Path) -> list[Path]:
    return [path for path in tmp_path.iterdir() if path.name.startswith("looplish-asr-")]


def test_small_file_is_delegated_without_probe(tmp_path: Path) -> None:
    media = FakeMediaProcessor()
    client = Client(Response(words((0.1, 0.5, "x"))))

    chunked(client, media).transcribe(audio_file(tmp_path, 1000), "en", None)

    assert media.probed == 0
    assert media.slices == []
    assert len(client.calls) == 1


def test_large_file_is_split_into_three_offset_chunks(tmp_path: Path) -> None:
    media = FakeMediaProcessor(duration=300.0)
    client = Client(
        chunk_response((1.0, 1.5, "one")),
        chunk_response((0.5, 1.0, "two")),
        chunk_response((2.0, 2.5, "three.")),
    )
    progress: list[float] = []

    transcript = chunked(client, media).transcribe(
        audio_file(tmp_path, 51_000_000), "en", lambda value, _: progress.append(value)
    )

    assert [(start, length) for _, start, length in media.slices] == [
        (0.0, 100.0),
        (100.0, 100.0),
        (200.0, 100.0),
    ]
    assert [(word.start, word.text) for word in transcript.words] == [
        (1.0, " one"),
        (100.5, " two"),
        (202.0, " three."),
    ]
    assert transcript.duration == 300.0
    assert transcript.source == "asr:openai:whisper-1"
    assert progress == pytest.approx([1 / 3, 2 / 3, 1.0])
    assert len(client.calls) == 3
    assert leftover_chunk_dirs(tmp_path) == []


def test_chunk_boundary_duplicates_are_dropped(tmp_path: Path) -> None:
    media = FakeMediaProcessor(duration=200.0)
    client = Client(
        chunk_response((99.0, 100.4, "split")),
        # 第二块开头重复识别了跨界的词，结束时间早于上一块最后一个词。
        chunk_response((0.0, 0.3, "split"), (0.5, 1.0, "next")),
    )

    transcript = chunked(client, media).transcribe(audio_file(tmp_path, 30_000_000), "en", None)

    assert [word.text for word in transcript.words] == [" split", " next"]
    ends = [word.end for word in transcript.words]
    assert ends == sorted(ends)


def test_reencoded_chunk_still_too_large_is_not_uploaded(tmp_path: Path) -> None:
    media = FakeMediaProcessor(chunk_bytes=25_000_001)
    client = Client(chunk_response((0.1, 0.2, "x")))

    with pytest.raises(ProcessingFailure, match="仍超过云端上传限制"):
        chunked(client, media).transcribe(audio_file(tmp_path, 51_000_000), "en", None)

    assert client.calls == []
    assert leftover_chunk_dirs(tmp_path) == []


def test_upload_failure_cleans_chunks_and_hides_key(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    media = FakeMediaProcessor()
    client = Client(chunk_response((0.1, 0.2, "x")), RuntimeError(f"boom {SECRET}"))

    with caplog.at_level(logging.DEBUG), pytest.raises(ProcessingFailure) as exc:
        chunked(client, media).transcribe(audio_file(tmp_path, 51_000_000), "en", None)

    assert exc.value.detail == "云端分块识别失败。"
    assert SECRET not in "".join(traceback.format_exception(exc.value))
    assert SECRET not in caplog.text
    assert leftover_chunk_dirs(tmp_path) == []


def test_progress_callback_failure_still_cleans_chunks(tmp_path: Path) -> None:
    media = FakeMediaProcessor()
    client = Client(chunk_response((0.1, 0.2, "x")))

    def broken(value: float, text: str) -> None:
        raise RuntimeError("callback failed")

    with pytest.raises(ProcessingFailure):
        chunked(client, media).transcribe(audio_file(tmp_path, 51_000_000), "en", broken)

    assert leftover_chunk_dirs(tmp_path) == []


def test_missing_words_in_a_chunk_fails_the_whole_transcription(tmp_path: Path) -> None:
    media = FakeMediaProcessor()
    client = Client(chunk_response((0.1, 0.2, "x")), Response([]))

    with pytest.raises(ProcessingFailure, match="词级时间戳"):
        chunked(client, media).transcribe(audio_file(tmp_path, 51_000_000), "en", None)

    assert leftover_chunk_dirs(tmp_path) == []


# ---------------------------------------------------------------- 时间轴整理


def test_timeline_repairs_zero_length_and_backward_words() -> None:
    transcript = build_transcript(
        [
            (0.5, 0.5, " zero", 0.9),
            (0.4, 0.8, " back", None),
            (1.0, 1.2, "   ", None),
            (1.3, 1.6, "\tkept", None),
        ],
        "en",
        2.0,
        "asr:test",
    )

    assert [(word.start, word.text) for word in transcript.words] == [
        (0.5, " zero"),
        (0.5, " back"),
        (1.3, "\tkept"),
    ]
    assert transcript.words[0].end == pytest.approx(0.501)
    assert transcript.words[0].probability == 0.9


def test_timeline_clamps_and_drops_words_past_media_end() -> None:
    transcript = build_transcript(
        [(1.0, 1.5, " in", None), (1.8, 2.4, " edge", None), (2.1, 2.5, " out", None)],
        None,
        2.0,
        "asr:test",
    )

    assert [word.text for word in transcript.words] == [" in", " edge"]
    assert transcript.words[-1].end == 2.0


def test_timeline_without_usable_words_fails() -> None:
    with pytest.raises(ProcessingFailure, match="词级时间戳"):
        build_transcript([(0.0, 0.5, " ", None)], "en", 2.0, "asr:test")


# ---------------------------------------------------------------- 本地后端


class FakeWord:
    def __init__(self, start: float, end: float, word: str, probability: float) -> None:
        self.start, self.end, self.word, self.probability = start, end, word, probability


class FakeSegment:
    def __init__(self, end: float, items: list[FakeWord] | None) -> None:
        self.end = end
        self.words = items


class FakeWhisperModel:
    def __init__(self, segments: list[FakeSegment], duration: float = 4.0) -> None:
        self.segments = segments
        self.duration = duration
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def transcribe(self, path: str, **kwargs: Any) -> tuple[Any, Any]:
        self.calls.append((path, kwargs))
        info = types.SimpleNamespace(duration=self.duration, language="en")
        return iter(self.segments), info


def test_local_backend_uses_exact_faster_whisper_parameters(tmp_path: Path) -> None:
    model = FakeWhisperModel([FakeSegment(1.0, [FakeWord(0.1, 0.5, " Hi.", 0.95)])])
    backend = LocalWhisperBackend("small.en", tmp_path, model=model)

    backend.transcribe(tmp_path / "in.wav", "en", None)

    assert model.calls == [
        (
            str(tmp_path / "in.wav"),
            {
                "language": "en",
                "word_timestamps": True,
                "vad_filter": True,
                "vad_parameters": {"min_silence_duration_ms": 300},
                "condition_on_previous_text": False,
            },
        )
    ]


def test_local_backend_maps_words_progress_and_detected_language(tmp_path: Path) -> None:
    model = FakeWhisperModel(
        [
            FakeSegment(
                2.0, [FakeWord(0.1, 0.5, " Hello", 0.9), FakeWord(0.6, 0.6, " there.", 0.8)]
            ),
            FakeSegment(4.0, None),
        ]
    )
    progress: list[tuple[float, str]] = []

    transcript = LocalWhisperBackend("small.en", tmp_path, model=model).transcribe(
        tmp_path / "in.wav", None, lambda value, text: progress.append((value, text))
    )

    assert [word.text for word in transcript.words] == [" Hello", " there."]
    assert transcript.words[1].end > transcript.words[1].start
    assert transcript.language == "en"
    assert transcript.duration == 4.0
    assert transcript.source == "asr:local:small.en"
    assert progress == [(0.5, "本地识别"), (1.0, "本地识别")]


def test_local_backend_without_words_fails(tmp_path: Path) -> None:
    model = FakeWhisperModel([FakeSegment(1.0, [])])

    with pytest.raises(ProcessingFailure, match="词级时间戳"):
        LocalWhisperBackend("small.en", tmp_path, model=model).transcribe(
            tmp_path / "in.wav", "en", None
        )


def test_local_model_errors_map_to_stable_error(tmp_path: Path) -> None:
    class Broken:
        def transcribe(self, *args: Any, **kwargs: Any) -> Any:
            raise RuntimeError("CUDA out of memory")

    with pytest.raises(ProcessingFailure) as exc:
        LocalWhisperBackend("small.en", tmp_path, model=Broken()).transcribe(
            tmp_path / "in.wav", "en", None
        )

    assert (exc.value.code, exc.value.detail) == ("TRANSCRIPTION_FAILED", "本地语音识别失败。")


def test_missing_faster_whisper_gives_install_hint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(sys.modules, "faster_whisper", None)

    with pytest.raises(ProcessingFailure, match="local-asr"):
        LocalWhisperBackend("small.en", tmp_path).transcribe(tmp_path / "in.wav", "en", None)


def test_model_is_loaded_lazily_once_with_configured_options(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    created: list[tuple[str, dict[str, Any]]] = []

    class WhisperModel(FakeWhisperModel):
        def __init__(self, name: str, **kwargs: Any) -> None:
            created.append((name, kwargs))
            super().__init__([FakeSegment(1.0, [FakeWord(0.1, 0.5, " ok", 0.9)])])

    monkeypatch.setitem(
        sys.modules, "faster_whisper", types.SimpleNamespace(WhisperModel=WhisperModel)
    )
    backend = LocalWhisperBackend("small.en", tmp_path / "models", "cpu", "int8")
    assert created == []

    threads = [
        threading.Thread(target=backend.transcribe, args=(tmp_path / "in.wav", "en", None))
        for _ in range(4)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert created == [
        (
            "small.en",
            {"device": "cpu", "compute_type": "int8", "download_root": str(tmp_path / "models")},
        )
    ]


# ---------------------------------------------------------------- Fake 与注册表


def test_fake_backend_is_deterministic(tmp_path: Path) -> None:
    seen: list[float] = []
    backend = FakeTranscriptionBackend()

    first = backend.transcribe(tmp_path / "x", None, lambda value, _: seen.append(value))
    second = backend.transcribe(tmp_path / "x", "fr", None)

    assert first.words == second.words
    assert first.language == "en"
    assert second.language == "fr"
    assert first.source == "asr:fake:fixture"
    assert seen == [1.0]


def settings(tmp_path: Path, **values: Any) -> Settings:
    return Settings(_env_file=None, data_dir=tmp_path / "jobs", **values)


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    import os

    for name in list(os.environ):
        if name.startswith("LOOPLISH_") or name.startswith("OPENAI_"):
            monkeypatch.delenv(name)


def test_registry_builds_fake_and_local(tmp_path: Path) -> None:
    media = FakeMediaProcessor()

    assert isinstance(
        build_backend(settings(tmp_path, asr_backend="fake"), media), FakeTranscriptionBackend
    )
    local = build_backend(
        settings(
            tmp_path,
            asr_backend="local",
            asr_model="base.en",
            asr_device="cpu",
            models_dir=tmp_path / "models",
        ),
        media,
    )
    assert isinstance(local, LocalWhisperBackend)
    assert (local.model_name, local.device, local.compute_type) == ("base.en", "cpu", "int8")
    assert local.models_dir == tmp_path / "models"
    # 构造时不加载模型、不导入 faster-whisper。
    assert local._model is None


@pytest.mark.parametrize(
    ("backend_name", "base_url", "model"),
    [
        ("openai", "https://api.openai.com/v1/", "whisper-1"),
        ("groq", GROQ_BASE_URL + "/", "whisper-large-v3-turbo"),
    ],
)
def test_registry_builds_chunked_cloud_backends(
    tmp_path: Path, backend_name: str, base_url: str, model: str
) -> None:
    backend = build_backend(
        settings(tmp_path, asr_backend=backend_name, asr_api_key=SECRET), FakeMediaProcessor()
    )

    assert isinstance(backend, ChunkedCloudBackend)
    assert backend.name == backend_name
    assert backend.max_upload_bytes == 24_000_000
    assert backend.delegate.max_upload_bytes == 25_000_000
    assert backend.delegate.model == model
    client = backend.delegate.client
    assert str(client.base_url) == base_url
    assert client.max_retries == 3
    assert client.timeout == 120.0
    assert SECRET not in repr(backend)
    assert SECRET not in repr(backend.delegate)


def test_registry_honours_custom_base_url_and_model(tmp_path: Path) -> None:
    backend = build_backend(
        settings(
            tmp_path,
            asr_backend="groq",
            asr_api_key=SECRET,
            asr_base_url="https://proxy.test/v1",
            asr_api_model="custom-model",
        ),
        FakeMediaProcessor(),
    )

    assert isinstance(backend, ChunkedCloudBackend)
    assert str(backend.delegate.client.base_url) == "https://proxy.test/v1/"
    assert backend.delegate.model == "custom-model"


def test_registry_rejects_unknown_backend(tmp_path: Path) -> None:
    # Settings 已在启动时拒绝未知名称；注册表对绕过校验的配置同样拒绝。
    unchecked = Settings.model_construct(asr_backend="missing")

    with pytest.raises(ValueError, match="unknown ASR backend"):
        build_backend(unchecked, FakeMediaProcessor())


def test_registry_rejects_cloud_backend_without_key(tmp_path: Path) -> None:
    unchecked = Settings.model_construct(asr_backend="openai", asr_api_key=None)

    with pytest.raises(ValueError, match="API key"):
        build_backend(unchecked, FakeMediaProcessor())


def test_key_never_reaches_transcript_or_persisted_result(tmp_path: Path) -> None:
    backend = build_backend(
        settings(tmp_path, asr_backend="openai", asr_api_key=SECRET), FakeMediaProcessor()
    )
    assert isinstance(backend, ChunkedCloudBackend)
    backend.delegate.client = Client(Response(words((0.1, 0.5, "Hi."))))

    transcript = backend.transcribe(audio_file(tmp_path), "en", None)
    sentences = build_sentences(transcript.words, transcript.duration, SegmentationOptions())
    result = JobResult(
        job_id="01JABCDEF123",
        title="t",
        source_url=None,
        uploader=None,
        thumbnail_url=None,
        duration=transcript.duration,
        language=transcript.language,
        transcript_source=transcript.source,
        audio_artifact="audio.m4a",
        created_at=datetime.now(UTC),
        sentences=sentences,
    )

    assert SECRET not in repr(transcript)
    assert SECRET not in transcript.source
    assert SECRET not in json.dumps(job_result_to_dict(result), ensure_ascii=False)
