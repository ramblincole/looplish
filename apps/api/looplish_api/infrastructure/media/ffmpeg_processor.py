import json
import math
from dataclasses import dataclass
from pathlib import Path

from looplish_api.domain.errors import ProcessingFailure
from looplish_api.infrastructure.media.command_runner import CommandRunner

# 练习页直接播放这个文件：AAC 原样拷贝不损失任何音质；其他编码转成 160k AAC 并保留立体声，
# 人声与背景音乐的空间分离有助于听清，混成单声道会让两者叠在一起。
# probe_audio 看的是 a:0，显式映射它，避免 ffmpeg 自选“最佳”音轨导致探测与处理不是同一条。
WEB_AUDIO_COPY = ["-map", "0:a:0", "-vn", "-c:a", "copy", "-movflags", "+faststart"]
WEB_AUDIO_ENCODE = ["-ar", "44100", "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart"]
ASR_WAV = ["-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le"]
ASR_MP3 = ["-vn", "-ac", "1", "-ar", "16000", "-c:a", "libmp3lame", "-b:a", "32k"]
CLIP_MP3 = ["-vn", "-ar", "44100", "-c:a", "libmp3lame", "-b:a", "128k"]


@dataclass(frozen=True, slots=True)
class AudioStream:
    codec: str
    channels: int


class FfmpegProcessor:
    def __init__(
        self,
        ffmpeg: str,
        ffprobe: str,
        runner: CommandRunner,
        max_media_seconds: float = 14_400,
    ) -> None:
        self.ffmpeg = ffmpeg
        self.ffprobe = ffprobe
        self.runner = runner
        self.max_media_seconds = max_media_seconds

    def probe_duration(self, source: Path) -> float:
        # ffprobe 只返回机器可读 JSON；时长在进入后续转码前统一校验。
        result = self.runner.run(
            [
                self.ffprobe,
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "json",
                str(source),
            ],
            timeout=30,
        )
        try:
            duration = float(json.loads(result.stdout)["format"]["duration"])
        except (ValueError, KeyError, TypeError) as error:
            # 没有音视频流的文件 ffprobe 会给出 N/A 或缺字段。
            raise ProcessingFailure("MEDIA_PROCESSING_FAILED", "无法读取媒体时长。") from error
        if not math.isfinite(duration) or duration <= 0:
            raise ProcessingFailure("MEDIA_PROCESSING_FAILED", "无法读取媒体时长。")
        if duration > self.max_media_seconds:
            raise ProcessingFailure("MEDIA_PROCESSING_FAILED", "媒体时长超过配置上限。")
        return duration

    def probe_audio(self, source: Path) -> AudioStream:
        result = self.runner.run(
            [
                self.ffprobe,
                "-v",
                "error",
                "-select_streams",
                "a:0",
                "-show_entries",
                "stream=codec_name,channels",
                "-of",
                "json",
                str(source),
            ],
            timeout=30,
        )
        try:
            stream = json.loads(result.stdout)["streams"][0]
            return AudioStream(str(stream["codec_name"]), int(stream["channels"]))
        except (ValueError, KeyError, IndexError, TypeError) as error:
            raise ProcessingFailure("MEDIA_PROCESSING_FAILED", "媒体中没有可用的音轨。") from error

    def _convert(
        self,
        source: Path,
        target: Path,
        options: list[str],
        input_options: tuple[str, ...] = (),
    ) -> Path:
        target.parent.mkdir(parents=True, exist_ok=True)
        # options 由下面的公开方法固定提供，不接受未经验证的 shell 字符串。
        self.runner.run(
            [
                self.ffmpeg,
                "-hide_banner",
                "-nostdin",
                "-y",
                *input_options,
                "-i",
                str(source),
                *options,
                str(target),
            ],
            timeout=3600,
        )
        return target

    @staticmethod
    def _window(start: float, duration: float) -> tuple[str, ...]:
        # -ss 放在 -i 之前直接定位到起点；重新编码时仍是采样级精确，长音频切片不必从头解码。
        return ("-ss", f"{start:.3f}", "-t", f"{duration:.3f}")

    def to_web_audio(self, source: Path, target: Path) -> Path:
        stream = self.probe_audio(source)
        if stream.codec == "aac":
            try:
                return self._convert(source, target, WEB_AUDIO_COPY)
            except ProcessingFailure:
                # 个别容器里的 AAC 无法直接封装进 MP4；删掉半成品后改为重新编码。
                target.unlink(missing_ok=True)
        # 只把多声道降到立体声；单声道和立体声保持原样。
        downmix = ["-ac", "2"] if stream.channels > 2 else []
        return self._convert(source, target, ["-map", "0:a:0", "-vn", *downmix, *WEB_AUDIO_ENCODE])

    def to_asr_wav(self, source: Path, target: Path) -> Path:
        return self._convert(source, target, ASR_WAV)

    def to_asr_mp3(self, source: Path, target: Path) -> Path:
        return self._convert(source, target, ASR_MP3)

    def slice_asr_mp3(self, source: Path, target: Path, start: float, duration: float) -> Path:
        return self._convert(source, target, ASR_MP3, self._window(start, duration))

    def slice_audio(self, source: Path, target: Path, start: float, duration: float) -> Path:
        return self._convert(source, target, CLIP_MP3, self._window(start, duration))
