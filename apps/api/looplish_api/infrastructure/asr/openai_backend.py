from __future__ import annotations

import logging
import math
import shutil
import tempfile
from pathlib import Path
from typing import Any

from looplish_api.domain.errors import ProcessingFailure
from looplish_api.domain.models import Transcript
from looplish_api.domain.ports import MediaProcessor, ProgressCallback
from looplish_api.infrastructure.asr.timeline import RawWord, build_transcript

logger = logging.getLogger(__name__)


def _value(item: object, name: str) -> Any:
    # 兼容 SDK 模型对象与测试/兼容服务返回的字典。
    if isinstance(item, dict):
        return item[name]
    return getattr(item, name)


def _describe(error: Exception) -> str:
    # 供应商错误正文可能回显部分 Key，只记录类型和 HTTP 状态码。
    status = getattr(error, "status_code", None)
    return type(error).__name__ if status is None else f"{type(error).__name__} (HTTP {status})"


def _cloud_failure(error: Exception, detail: str) -> ProcessingFailure:
    logger.warning("cloud transcription failed: %s", _describe(error))
    return ProcessingFailure("TRANSCRIPTION_FAILED", detail, 502)


class OpenAICompatibleBackend:
    def __init__(
        self,
        name: str,
        client: Any,
        model: str,
        max_upload_bytes: int,
    ) -> None:
        self.name = name
        self.client = client
        self.model = model
        self.max_upload_bytes = max_upload_bytes

    @property
    def source(self) -> str:
        return f"asr:{self.name}:{self.model}"

    def _one(self, path: Path, language: str | None, offset: float) -> tuple[list[RawWord], float]:
        with path.open("rb") as handle:
            response = self.client.audio.transcriptions.create(
                model=self.model,
                file=handle,
                language=language,
                response_format="verbose_json",
                timestamp_granularities=["word"],
            )
        raw_words = getattr(response, "words", None)
        # 词级时间戳是下游切句的硬契约，不能静默退化为段级数据。
        if not raw_words:
            raise ProcessingFailure(
                "TRANSCRIPTION_FAILED",
                "云端模型未返回词级时间戳，请更换支持 words 的模型。",
                502,
            )
        words: list[RawWord] = [
            (
                offset + float(_value(item, "start")),
                offset + float(_value(item, "end")),
                str(_value(item, "word")),
                None,
            )
            for item in raw_words
        ]
        duration = getattr(response, "duration", None)
        return words, float(duration) if duration else words[-1][1] - offset

    def transcribe(
        self,
        audio_path: Path,
        language: str | None,
        progress: ProgressCallback | None,
    ) -> Transcript:
        if audio_path.stat().st_size > self.max_upload_bytes:
            raise ProcessingFailure(
                "TRANSCRIPTION_FAILED",
                "识别文件超过单次上传限制，必须先由 ChunkedCloudBackend 分块。",
                502,
            )
        try:
            words, duration = self._one(audio_path, language, 0.0)
        except ProcessingFailure:
            raise
        except Exception as error:
            # 不链接原异常：它的消息可能含有供应商回显的 Key 片段，会随日志堆栈泄露。
            raise _cloud_failure(error, "云端语音识别失败。") from None
        if progress is not None:
            progress(1.0, "云端识别完成")
        return build_transcript(words, language, duration, self.source)


class ChunkedCloudBackend:
    def __init__(
        self,
        delegate: OpenAICompatibleBackend,
        media: MediaProcessor,
        max_upload_bytes: int = 24_000_000,
    ) -> None:
        self.delegate = delegate
        self.media = media
        self.max_upload_bytes = max_upload_bytes
        self.name = delegate.name

    def transcribe(
        self,
        audio_path: Path,
        language: str | None,
        progress: ProgressCallback | None,
    ) -> Transcript:
        size = audio_path.stat().st_size
        if size <= self.max_upload_bytes:
            # 小文件直接委托，保留 delegate 自己的进度和错误映射。
            return self.delegate.transcribe(audio_path, language, progress)
        duration = self.media.probe_duration(audio_path)
        count = math.ceil(size / self.max_upload_bytes)
        chunk_duration = duration / count
        words: list[RawWord] = []
        temporary = Path(tempfile.mkdtemp(prefix="looplish-asr-", dir=audio_path.parent))
        try:
            for index in range(count):
                offset = index * chunk_duration
                length = min(chunk_duration, duration - offset)
                chunk = temporary / f"{index + 1:04}.mp3"
                # 云端专用 32 kbps 单声道切片，不能误用 128 kbps 的练习切片。
                self.media.slice_asr_mp3(audio_path, chunk, offset, length)
                if chunk.stat().st_size > self.delegate.max_upload_bytes:
                    raise ProcessingFailure(
                        "TRANSCRIPTION_FAILED",
                        "分块重编码后仍超过云端上传限制。",
                        502,
                    )
                chunk_words, _ = self.delegate._one(chunk, language, offset)
                last_end = words[-1][1] if words else -1.0
                # 丢弃切块边界的重复词，保证合并后的结束时间单调。
                words.extend(word for word in chunk_words if word[1] > last_end)
                if progress is not None:
                    progress((index + 1) / count, f"云端识别 {index + 1}/{count}")
        except ProcessingFailure:
            raise
        except Exception as error:
            raise _cloud_failure(error, "云端分块识别失败。") from None
        finally:
            # 无论上传、解析还是进度回调在哪一处失败，都删除全部切片。
            shutil.rmtree(temporary, ignore_errors=True)
        return build_transcript(words, language, duration, self.delegate.source)
