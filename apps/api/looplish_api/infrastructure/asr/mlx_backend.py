import importlib
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from threading import Lock
from types import SimpleNamespace
from typing import Any

from looplish_api.domain.errors import ProcessingFailure
from looplish_api.domain.models import Transcript
from looplish_api.domain.ports import ProgressCallback
from looplish_api.infrastructure.asr.local_backend import missing_dependency
from looplish_api.infrastructure.asr.local_progress import LocalProgress
from looplish_api.infrastructure.asr.model_store import ensure_model
from looplish_api.infrastructure.asr.prompting import decoding_options
from looplish_api.infrastructure.asr.timeline import RawWord, build_transcript

SAMPLE_RATE = 16_000
# mlx-whisper 的进度以梅尔帧计，每帧 10 ms。
FRAMES_PER_SECOND = 100
MODEL_FILES = ["config.json", "weights.*"]

# 与 faster-whisper 同名的模型对应到 mlx-community 转换好的权重；没有对应项时不用 MLX。
_SIZES = ("tiny", "base", "small", "medium")
MLX_MODELS: dict[str, str] = {
    **{size: f"mlx-community/whisper-{size}-mlx" for size in _SIZES},
    **{f"{size}.en": f"mlx-community/whisper-{size}.en-mlx" for size in _SIZES},
    "large-v2": "mlx-community/whisper-large-v2-mlx",
    "large-v3": "mlx-community/whisper-large-v3-mlx",
    "large": "mlx-community/whisper-large-v3-mlx",
    "large-v3-turbo": "mlx-community/whisper-large-v3-turbo",
    "turbo": "mlx-community/whisper-large-v3-turbo",
}


def mlx_repo(model_name: str) -> str | None:
    if model_name.startswith("mlx-community/"):
        return model_name
    return MLX_MODELS.get(model_name)


class _FrameCounter:
    """顶替 mlx-whisper 内部的 tqdm，把已解码的帧数交给回调。"""

    def __init__(self, on_frames: Callable[[int], None], **_: Any) -> None:
        self.frames = 0
        self.on_frames = on_frames

    def __enter__(self) -> "_FrameCounter":
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def update(self, n: int) -> None:
        self.frames += n
        self.on_frames(self.frames)


@contextmanager
def _frame_progress(on_frames: Callable[[int], None]) -> Iterator[None]:
    # mlx-whisper 没有进度回调，只在 verbose=False 时更新一个 tqdm 进度条；
    # 调用期间替换它所在模块的 tqdm 引用。调用方持有锁，不会有并发识别互相覆盖。
    module = importlib.import_module("mlx_whisper.transcribe")
    original = getattr(module, "tqdm")  # noqa: B009
    counter = SimpleNamespace(tqdm=lambda **kwargs: _FrameCounter(on_frames, **kwargs))
    setattr(module, "tqdm", counter)  # noqa: B010
    try:
        yield
    finally:
        setattr(module, "tqdm", original)  # noqa: B010


class MlxWhisperBackend:
    """Apple 芯片上用 GPU 推理的本地识别；人声检测沿用 faster-whisper 的 Silero VAD。"""

    name = "local"

    def __init__(self, model_name: str, repo_id: str, models_dir: Path) -> None:
        self.model_name = model_name
        self.repo_id = repo_id
        self.models_dir = models_dir
        self._model_path: Path | None = None
        # MLX 模型是进程级缓存，进度替换也是模块级的，识别必须串行。
        self._lock = Lock()

    def transcribe(
        self,
        audio_path: Path,
        language: str | None,
        progress: ProgressCallback | None,
    ) -> Transcript:
        report = LocalProgress(progress)
        try:
            import mlx_whisper
            import numpy as np
            from faster_whisper.audio import decode_audio
            from faster_whisper.vad import (
                SpeechTimestampsMap,
                VadOptions,
                collect_chunks,
                get_speech_timestamps,
            )
        except ImportError as error:
            raise missing_dependency() from error
        with self._lock:
            try:
                if self._model_path is None:
                    self._model_path = ensure_model(
                        self.repo_id, self.models_dir, report.model_download, MODEL_FILES
                    )
                    report.model_loading()
                audio = decode_audio(str(audio_path), sampling_rate=SAMPLE_RATE)
                duration = len(audio) / SAMPLE_RATE
                report.detecting_speech()
                # 同 faster-whisper 的 vad_filter：只拼接人声片段送去识别，再换算回原时间轴。
                speech = get_speech_timestamps(audio, VadOptions(min_silence_duration_ms=300))
                if not speech:
                    raise ProcessingFailure("TRANSCRIPTION_FAILED", "没有识别到人声。", 502)
                chunks, _ = collect_chunks(audio, speech, sampling_rate=SAMPLE_RATE)
                timeline = SpeechTimestampsMap(speech, SAMPLE_RATE)

                def on_frames(frames: int) -> None:
                    report.recognized(
                        timeline.get_original_time(frames / FRAMES_PER_SECOND), duration
                    )

                with _frame_progress(on_frames):
                    result = mlx_whisper.transcribe(
                        np.concatenate(chunks),
                        path_or_hf_repo=str(self._model_path),
                        language=language,
                        word_timestamps=True,
                        verbose=False,
                        **decoding_options(language),
                    )
            except ProcessingFailure:
                raise
            except Exception as error:
                raise ProcessingFailure(
                    "TRANSCRIPTION_FAILED", "本地语音识别失败。", 502
                ) from error
        words: list[RawWord] = []
        for segment in result.get("segments", ()):
            for item in segment.get("words") or ():
                start, end = float(item["start"]), float(item["end"])
                # 同一个词的起止要落在同一个人声片段里，否则跨过被剔除的静音会被拉长。
                chunk = timeline.get_chunk_index((start + end) / 2)
                words.append(
                    (
                        timeline.get_original_time(start, chunk),
                        timeline.get_original_time(end, chunk),
                        str(item["word"]),
                        float(item.get("probability", 0.0)),
                    )
                )
        detected = language or result.get("language")
        return build_transcript(words, detected, duration, f"asr:local:{self.model_name}")
