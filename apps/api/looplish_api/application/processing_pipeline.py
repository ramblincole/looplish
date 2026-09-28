from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from looplish_api.application.exporter import ArtifactExporter
from looplish_api.application.progress import ProgressReporter, pipeline_stages
from looplish_api.domain.errors import InvalidJobOptions, ProcessingFailure
from looplish_api.domain.models import JobOptions, JobResult, JobStage, SubtitleSource, Transcript
from looplish_api.domain.ports import (
    ArtifactStore,
    JobRepository,
    MediaDownloader,
    MediaProcessor,
    TranscriptionBackend,
)
from looplish_api.domain.segmentation import build_sentences
from looplish_api.infrastructure.subtitles.parser import parse_subtitle, select_subtitle

ProgressSink = Callable[[str, JobStage, float, str], None]


def is_url(source: str) -> bool:
    return source.startswith(("http://", "https://"))


class ProcessingPipeline:
    def __init__(
        self,
        repository: JobRepository,
        store: ArtifactStore,
        downloader: MediaDownloader,
        media: MediaProcessor,
        transcribers: dict[str, TranscriptionBackend],
        exporter: ArtifactExporter,
        progress: ProgressSink,
    ) -> None:
        self.repository = repository
        self.store = store
        self.downloader = downloader
        self.media = media
        self.transcribers = transcribers
        self.exporter = exporter
        self.progress = progress

    def _subtitle(
        self,
        job_id: str,
        duration: float,
        options: JobOptions,
    ) -> Transcript | None:
        source_dir = self.store.source_dir(job_id)
        selected = select_subtitle(
            tuple(source_dir.glob("*.vtt")) + tuple(source_dir.glob("*.srt")),
            options.subtitle_languages,
        )
        if selected is None:
            return None
        try:
            return parse_subtitle(selected, duration)
        except ValueError:
            # 字幕为空或编码无法读取时视同没有字幕：auto 回退到识别，existing 由调用方报错。
            return None

    def _transcribe(
        self, job_id: str, source: Path, options: JobOptions, reporter: ProgressReporter
    ) -> Transcript:
        backend = self.transcribers.get(options.asr_backend)
        if backend is None:
            raise InvalidJobOptions("该 ASR 后端未在当前进程中配置。")
        asr_source = self.store.artifact_path(
            job_id,
            "asr-input.wav" if options.asr_backend == "local" else "asr-upload.mp3",
        )
        try:
            # 本地与云端后端消费不同编码，统一在这里准备一次性输入。
            if options.asr_backend == "local":
                self.media.to_asr_wav(source, asr_source)
            else:
                self.media.to_asr_mp3(source, asr_source)
            return backend.transcribe(
                asr_source,
                options.language,
                lambda value, text: reporter.report(JobStage.TRANSCRIBING, value, text),
            )
        finally:
            # ASR 输入是中间产物，识别成功或失败都不保留。
            asr_source.unlink(missing_ok=True)

    def run(self, job_id: str) -> JobResult:
        job = self.repository.get(job_id)
        if job is None or job.options is None:
            raise ValueError("queued job and options are required")
        options = job.options
        downloads = is_url(job.source)
        reporter = ProgressReporter(
            pipeline_stages(downloads),
            lambda stage, value, message: self.progress(job_id, stage, value, message),
        )
        source = Path(job.source)
        title = job.title
        source_url = None
        uploader = None
        thumbnail_url = None
        # URL 任务先下载；上传和本机文件的 source 已是本机路径，跳过下载器。
        if downloads:
            reporter.report(JobStage.DOWNLOADING, 0.0, "下载媒体")
            media_info = self.downloader.download(
                job.source, self.store.source_dir(job_id), options.subtitle_languages
            )
            source = media_info.path
            title = media_info.title
            source_url = media_info.source_url
            uploader = media_info.uploader
            thumbnail_url = media_info.thumbnail_url
            reporter.report(JobStage.DOWNLOADING, 1.0, "下载完成")
        reporter.report(JobStage.PREPARING_AUDIO, 0.0, "准备音频")
        duration = self.media.probe_duration(source)
        web_audio = self.media.to_web_audio(source, self.store.artifact_path(job_id, "audio.m4a"))
        reporter.report(JobStage.PREPARING_AUDIO, 1.0, "音频准备完成")
        transcript = None
        # auto/existing 先尝试人工字幕；明确选择 ASR 时完全跳过字幕查找。
        if options.subtitle_source is not SubtitleSource.ASR:
            reporter.report(JobStage.TRANSCRIBING, 0.0, "解析字幕")
            transcript = self._subtitle(job_id, duration, options)
        if transcript is None and options.subtitle_source is SubtitleSource.EXISTING:
            raise ProcessingFailure("SUBTITLE_NOT_AVAILABLE", "没有可用的人工字幕。")
        if transcript is None:
            reporter.report(JobStage.TRANSCRIBING, 0.0, "开始识别")
            transcript = self._transcribe(job_id, source, options, reporter)
        reporter.report(JobStage.TRANSCRIBING, 1.0, "转写完成")
        reporter.report(JobStage.SEGMENTING, 0.0, "智能切句")
        # 识别用的是转码后的音频，时长可能比原媒体多几毫秒；以较长者为准，避免末尾的词被判越界。
        timeline = max(duration, transcript.duration)
        sentences = build_sentences(transcript.words, timeline, options.segmentation)
        result = JobResult(
            job_id=job_id,
            title=title,
            source_url=source_url,
            uploader=uploader,
            thumbnail_url=thumbnail_url,
            duration=timeline,
            language=transcript.language or options.language,
            transcript_source=transcript.source,
            audio_artifact=web_audio.name,
            created_at=datetime.now(UTC),
            sentences=sentences,
            has_clips=False,
        )
        self.exporter.write_text_artifacts(result)
        if options.make_clips:
            # 只在显式请求时预生成全部练习切片，否则后续可按需生成。
            for index in range(len(sentences)):
                self.exporter.ensure_clip(result, index)
                reporter.report(JobStage.SEGMENTING, (index + 1) / len(sentences), "生成切片")
            result = replace(result, has_clips=True)
        self.store.write_result(job_id, result)
        reporter.report(JobStage.SEGMENTING, 1.0, "处理完成")
        return result
