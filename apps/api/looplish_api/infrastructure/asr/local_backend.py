from pathlib import Path
from threading import Lock
from typing import Any

from looplish_api.domain.errors import ProcessingFailure
from looplish_api.domain.models import Transcript
from looplish_api.domain.ports import ProgressCallback
from looplish_api.infrastructure.asr.local_progress import LocalProgress
from looplish_api.infrastructure.asr.model_store import ensure_model
from looplish_api.infrastructure.asr.prompting import decoding_options
from looplish_api.infrastructure.asr.timeline import RawWord, build_transcript

# 与 faster_whisper.utils.download_model 下载的文件一致，已有缓存可直接复用。
MODEL_FILES = [
    "config.json",
    "preprocessor_config.json",
    "model.bin",
    "tokenizer.json",
    "vocabulary.*",
]


def missing_dependency() -> ProcessingFailure:
    return ProcessingFailure(
        "TRANSCRIPTION_FAILED",
        "本地识别需要安装可选依赖 faster-whisper（uv sync --extra local-asr）。",
        502,
    )


class LocalWhisperBackend:
    name = "local"

    def __init__(
        self,
        model_name: str,
        models_dir: Path,
        device: str = "auto",
        compute_type: str = "int8",
        cpu_threads: int = 0,
        model: Any | None = None,
    ) -> None:
        self.model_name = model_name
        self.models_dir = models_dir
        self.device = device
        self.compute_type = compute_type
        self.cpu_threads = cpu_threads
        self._model = model
        self._lock = Lock()

    def _model_path(self, report: LocalProgress) -> str:
        # 本机目录直接使用；其余按 faster-whisper 的别名表换成 Hugging Face 仓库再取本地缓存。
        if Path(self.model_name).expanduser().is_dir():
            return str(Path(self.model_name).expanduser())
        from faster_whisper import utils

        repo_id = getattr(utils, "_MODELS", {}).get(self.model_name, self.model_name)
        if "/" not in repo_id:
            raise ProcessingFailure("TRANSCRIPTION_FAILED", "未知的本地识别模型。", 502)
        return str(ensure_model(repo_id, self.models_dir, report.model_download, MODEL_FILES))

    def _load(self, report: LocalProgress) -> Any:
        # 多个任务线程同时首次识别时只加载一次模型。
        with self._lock:
            if self._model is None:
                # 延迟导入和建模，避免未选择 local 时加载大型依赖或下载模型。
                try:
                    from faster_whisper import WhisperModel
                except ImportError as error:
                    raise missing_dependency() from error
                path = self._model_path(report)
                report.model_loading()
                # 不用批量管线：批量模式各段独立解码，标点无法延续，整段容易漏标点。
                self._model = WhisperModel(
                    path,
                    device=self.device,
                    compute_type=self.compute_type,
                    cpu_threads=self.cpu_threads,
                )
            return self._model

    def transcribe(
        self,
        audio_path: Path,
        language: str | None,
        progress: ProgressCallback | None,
    ) -> Transcript:
        report = LocalProgress(progress)
        try:
            model = self._load(report)
            report.detecting_speech()
            segments, info = model.transcribe(
                str(audio_path),
                language=language,
                word_timestamps=True,
                vad_filter=True,
                vad_parameters={"min_silence_duration_ms": 300},
                **decoding_options(language),
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
                if info.duration:
                    report.recognized(float(segment.end), float(info.duration))
            duration = float(info.duration)
            # 未指定语言时使用模型检测出的语言。
            detected = language or getattr(info, "language", None)
        except ProcessingFailure:
            raise
        except Exception as error:
            raise ProcessingFailure("TRANSCRIPTION_FAILED", "本地语音识别失败。", 502) from error
        return build_transcript(words, detected, duration, f"asr:local:{self.model_name}")
