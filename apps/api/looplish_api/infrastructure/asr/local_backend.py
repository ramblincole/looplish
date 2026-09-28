from pathlib import Path
from threading import Lock
from typing import Any

from looplish_api.domain.errors import ProcessingFailure
from looplish_api.domain.models import Transcript
from looplish_api.domain.ports import ProgressCallback
from looplish_api.infrastructure.asr.timeline import RawWord, build_transcript


class LocalWhisperBackend:
    name = "local"

    def __init__(
        self,
        model_name: str,
        models_dir: Path,
        device: str = "auto",
        compute_type: str = "int8",
        model: Any | None = None,
    ) -> None:
        self.model_name = model_name
        self.models_dir = models_dir
        self.device = device
        self.compute_type = compute_type
        self._model = model
        self._lock = Lock()

    def _load(self) -> Any:
        # 多个任务线程同时首次识别时只加载一次模型。
        with self._lock:
            if self._model is None:
                # 延迟导入和建模，避免未选择 local 时加载大型依赖或下载模型。
                try:
                    from faster_whisper import WhisperModel
                except ImportError as error:
                    raise ProcessingFailure(
                        "TRANSCRIPTION_FAILED",
                        "本地识别需要安装可选依赖 faster-whisper（uv sync --extra local-asr）。",
                        502,
                    ) from error
                self._model = WhisperModel(
                    self.model_name,
                    device=self.device,
                    compute_type=self.compute_type,
                    download_root=str(self.models_dir),
                )
            return self._model

    def transcribe(
        self,
        audio_path: Path,
        language: str | None,
        progress: ProgressCallback | None,
    ) -> Transcript:
        try:
            segments, info = self._load().transcribe(
                str(audio_path),
                language=language,
                word_timestamps=True,
                vad_filter=True,
                vad_parameters={"min_silence_duration_ms": 300},
                condition_on_previous_text=False,
            )
            words: list[RawWord] = []
            for segment in segments:
                # 只接收词级结果；segment 仅用于遍历和估算阶段进度。
                for item in segment.words or ():
                    words.append(
                        (
                            float(item.start),
                            float(item.end),
                            str(item.word),
                            float(item.probability),
                        )
                    )
                if progress is not None and info.duration:
                    progress(min(1.0, float(segment.end) / float(info.duration)), "本地识别")
            duration = float(info.duration)
            # 未指定语言时使用模型检测出的语言。
            detected = language or getattr(info, "language", None)
        except ProcessingFailure:
            raise
        except Exception as error:
            raise ProcessingFailure("TRANSCRIPTION_FAILED", "本地语音识别失败。", 502) from error
        return build_transcript(words, detected, duration, f"asr:local:{self.model_name}")
