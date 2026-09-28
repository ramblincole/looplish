from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Request

from looplish_api.application.exporter import ArtifactExporter
from looplish_api.application.job_runner import JobRunner
from looplish_api.application.job_service import JobService
from looplish_api.application.processing_pipeline import ProcessingPipeline
from looplish_api.application.progress import ThrottledProgressSink
from looplish_api.config import Settings
from looplish_api.domain.ports import JobRepository, MediaProcessor
from looplish_api.infrastructure.asr.registry import build_backend
from looplish_api.infrastructure.media.command_runner import CommandRunner
from looplish_api.infrastructure.media.ffmpeg_processor import FfmpegProcessor
from looplish_api.infrastructure.media.ytdlp_downloader import YtDlpDownloader
from looplish_api.infrastructure.storage.file_artifact_store import FileArtifactStore
from looplish_api.infrastructure.storage.json_job_repository import JsonJobRepository


@dataclass(frozen=True)
class Container:
    settings: Settings
    service: JobService
    runner: JobRunner
    store: FileArtifactStore
    repository: JobRepository
    media: MediaProcessor
    exporter: ArtifactExporter


def build_container(settings: Settings) -> Container:
    # 装配顺序固定：存储 → 媒体 → 下载 → 识别 → 编排；整张实例图只构造一次并共享。
    store = FileArtifactStore(settings.data_dir)
    repository = JsonJobRepository(store)
    media = FfmpegProcessor(
        settings.ffmpeg_path,
        settings.ffprobe_path,
        CommandRunner(),
        max_media_seconds=settings.max_media_seconds,
    )
    downloader = YtDlpDownloader(settings.max_download_bytes)
    backend = build_backend(settings, media)
    exporter = ArtifactExporter(store, media)
    # 进度 sink 只依赖仓库，先于流水线创建，不与 Service/Runner 形成循环依赖。
    progress = ThrottledProgressSink(repository)
    pipeline = ProcessingPipeline(
        repository,
        store,
        downloader,
        media,
        {backend.name: backend},
        exporter,
        progress,
    )
    runner = JobRunner(pipeline, max_workers=settings.max_workers)
    service = JobService(
        repository,
        store,
        runner,
        exporter,
        settings.max_upload_bytes,
        allow_local_paths=settings.local_paths_enabled,
    )
    return Container(settings, service, runner, store, repository, media, exporter)


def get_container(request: Request) -> Container:
    container: Container = request.app.state.container
    return container


ContainerDep = Annotated[Container, Depends(get_container)]
