from __future__ import annotations

import csv
import io
import os
import tempfile
import zipfile
from pathlib import Path

from looplish_api.domain.models import JobResult, Sentence
from looplish_api.domain.ports import MediaProcessor
from looplish_api.infrastructure.storage.file_artifact_store import FileArtifactStore

TEXT_ARTIFACTS = (
    "subtitles.srt",
    "subtitles.vtt",
    "sentences.txt",
    "anki_import.tsv",
)
README = (
    "Looplish export\n"
    "subtitles.srt/vtt: speech boundaries\n"
    "clips: padded practice audio\n"
    "anki_import.tsv: import with media files from clips/\n"
)


def clip_name(index: int) -> str:
    # API 的句子索引从 0 开始，文件名从 000001 开始。
    return f"{index + 1:06}.mp3"


def _timestamp(seconds: float, separator: str) -> str:
    # 统一先舍入到毫秒，并把负数夹到零，避免两种字幕格式产生漂移。
    milliseconds = max(0, round(seconds * 1000))
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    whole_seconds, millis = divmod(remainder, 1000)
    return f"{hours:02}:{minutes:02}:{whole_seconds:02}{separator}{millis:03}"


def _one_line(text: str) -> str:
    # 字幕块以空行分隔、纯文本一行一句，句内换行必须压成空格。
    return " ".join(text.split())


def _vtt_escape(text: str) -> str:
    # VTT 文本按 HTML 解析，`&`、`<`、`>` 必须写成实体。
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def render_srt(sentences: tuple[Sentence, ...]) -> str:
    blocks = []
    for sentence in sentences:
        blocks.append(
            f"{sentence.index + 1}\n"
            f"{_timestamp(sentence.speech_start, ',')} --> "
            f"{_timestamp(sentence.speech_end, ',')}\n"
            f"{_one_line(sentence.text)}\n"
        )
    return "\n".join(blocks)


def render_vtt(sentences: tuple[Sentence, ...]) -> str:
    cues = []
    for sentence in sentences:
        cues.append(
            f"{_timestamp(sentence.speech_start, '.')} --> "
            f"{_timestamp(sentence.speech_end, '.')}\n"
            f"{_vtt_escape(_one_line(sentence.text))}\n"
        )
    return "WEBVTT\n\n" + "\n".join(cues)


def render_text(sentences: tuple[Sentence, ...]) -> str:
    return "".join(f"{_one_line(sentence.text)}\n" for sentence in sentences)


def render_anki(sentences: tuple[Sentence, ...]) -> str:
    output = io.StringIO(newline="")
    writer = csv.writer(
        output, dialect="excel-tab", lineterminator="\r\n", quoting=csv.QUOTE_MINIMAL
    )
    for sentence in sentences:
        writer.writerow([f"[sound:{clip_name(sentence.index)}]", sentence.text])
    return output.getvalue()


def _temporary_sibling(target: Path, suffix: str) -> Path:
    # 临时文件与目标同目录且名字唯一，并发生成互不覆盖，os.replace 保持原子。
    descriptor, name = tempfile.mkstemp(dir=target.parent, prefix=f".{target.stem}.", suffix=suffix)
    os.close(descriptor)
    return Path(name)


def _atomic_write_text(target: Path, value: str) -> None:
    temporary = _temporary_sibling(target, ".tmp")
    try:
        temporary.write_text(value, encoding="utf-8", newline="\n")
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


class ArtifactExporter:
    def __init__(self, store: FileArtifactStore, media: MediaProcessor) -> None:
        self.store = store
        self.media = media

    def write_text_artifacts(self, result: JobResult) -> None:
        values = {
            "subtitles.srt": render_srt(result.sentences),
            "subtitles.vtt": render_vtt(result.sentences),
            "sentences.txt": render_text(result.sentences),
            "anki_import.tsv": render_anki(result.sentences),
        }
        for name, value in values.items():
            target = self.store.artifact_path(result.job_id, name)
            target.parent.mkdir(parents=True, exist_ok=True)
            _atomic_write_text(target, value)

    def ensure_clip(self, result: JobResult, index: int) -> Path:
        if index < 0 or index >= len(result.sentences):
            raise IndexError("sentence index out of range")
        target = self.store.clips_dir(result.job_id) / clip_name(index)
        # 已有切片视为完成缓存，重复导出不再次调用媒体处理器。
        if target.exists():
            return target
        sentence = result.sentences[index]
        source = self.store.artifact_path(result.job_id, result.audio_artifact)
        # 先切到临时文件再改名，切片失败或中断不会留下被当作缓存的半截文件。
        temporary = _temporary_sibling(target, ".mp3")
        try:
            self.media.slice_audio(source, temporary, sentence.start, sentence.duration)
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)
        return target

    def build_bundle(self, result: JobResult, include_clips: bool = True) -> Path:
        self.write_text_artifacts(result)
        clips: list[Path] = []
        if include_clips:
            clips = [self.ensure_clip(result, index) for index in range(len(result.sentences))]
        target = self.store.artifact_path(result.job_id, "bundle.zip")
        # 先写同目录临时包，完整关闭 ZIP 后再替换正式产物。
        temporary = _temporary_sibling(target, ".tmp")
        try:
            with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                for name in TEXT_ARTIFACTS:
                    archive.write(self.store.artifact_path(result.job_id, name), arcname=name)
                archive.writestr("README.txt", README)
                # 归档名只来自句子序号，不扫描目录，旧切片和临时文件都不会混进来。
                for index, clip in enumerate(clips):
                    archive.write(clip, arcname=f"clips/{clip_name(index)}")
            os.replace(temporary, target)
        finally:
            # 写包或替换失败时清理临时文件，旧的正式 bundle 仍保持可读。
            temporary.unlink(missing_ok=True)
        return target
