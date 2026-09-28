import asyncio
import logging
import os
import re
import secrets
import shutil
import tempfile
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock

from looplish_api.application.commands import (
    CreateJobCommand,
    ResegmentCommand,
    UploadJobCommand,
    UploadStream,
)
from looplish_api.application.exporter import ArtifactExporter
from looplish_api.application.job_runner import JobRunner
from looplish_api.application.processing_pipeline import is_url
from looplish_api.domain.errors import (
    ArtifactNotFound,
    DomainError,
    JobNotFound,
    JobNotReady,
    JobRunning,
    LocalPathsDisabled,
    SentenceNotFound,
    ServiceStopping,
    SourceNotSupported,
    UploadTooLarge,
    WordsNotAvailable,
)
from looplish_api.domain.models import (
    Job,
    JobPage,
    JobQuery,
    JobResult,
    JobStatus,
    Problem,
)
from looplish_api.domain.ports import ArtifactStore, JobRepository
from looplish_api.domain.segmentation import build_sentences

logger = logging.getLogger(__name__)
UPLOAD_CHUNK_BYTES = 1_048_576
UNSAFE_FILENAME = re.compile(r"[^A-Za-z0-9._-]")
MAX_FILENAME_LENGTH = 100
# 字幕格式到产物名的固定映射，客户端只能在这三个里选。
SUBTITLE_ARTIFACTS = {"srt": "subtitles.srt", "vtt": "subtitles.vtt", "txt": "sentences.txt"}


def new_job_id() -> str:
    # 16 位不可预测的大写十六进制，满足存储层的任务 ID 格式。
    return secrets.token_hex(8).upper()


def safe_upload_name(filename: str) -> str:
    # 只取 basename，非安全字符替换为下划线；去掉开头的点，`..` 这类名字不会越出目录。
    cleaned = UNSAFE_FILENAME.sub("_", Path(filename.replace("\\", "/")).name).lstrip(".")
    cleaned = cleaned[-MAX_FILENAME_LENGTH:] or "upload"
    # 固定前缀同时避开 Windows 的保留设备名（CON、NUL 等）。
    return f"source-{cleaned}"


class JobService:
    def __init__(
        self,
        repository: JobRepository,
        store: ArtifactStore,
        runner: JobRunner,
        exporter: ArtifactExporter,
        max_upload_bytes: int,
        allow_local_paths: bool = True,
    ) -> None:
        self.repository = repository
        self.store = store
        self.runner = runner
        self.exporter = exporter
        self.max_upload_bytes = max_upload_bytes
        self.allow_local_paths = allow_local_paths
        # 重切句会重写结果、字幕并删除切片；切片和素材包生成与它互斥，避免按旧句子写出切片。
        self._artifact_lock = RLock()

    def _ensure_accepting(self) -> None:
        if self.runner.stopping.is_set():
            raise ServiceStopping()

    def _enqueue(self, job: Job) -> Job:
        # 先原子保存 queued，再入队；入队失败时任务落为 failed 并返回稳定错误。
        self.repository.save(job)
        try:
            self.runner.submit(job.id)
        except DomainError as error:
            failed = job.transition(
                JobStatus.FAILED,
                datetime.now(UTC),
                message="任务未能入队",
                error=Problem(error.code, error.detail),
            )
            self.repository.save(failed)
            raise
        logger.info("job queued", extra={"event": "job.queued", "jobId": job.id})
        return job

    def create_from_source(self, command: CreateJobCommand) -> Job:
        self._ensure_accepting()
        source = command.source.strip()
        if is_url(source):
            title = source
        elif not self.allow_local_paths:
            # 先于任何文件系统访问拒绝，不透露服务器上某个路径是否存在。
            raise LocalPathsDisabled()
        else:
            path = Path(source).expanduser()
            if not path.is_absolute() or not path.is_file():
                raise SourceNotSupported("只支持 HTTP(S) URL 或已存在的本机文件。")
            source = str(path.resolve())
            title = path.name
        job = replace(Job.new(new_job_id(), source, title), options=command.options)
        return self._enqueue(job)

    async def create_from_upload(self, upload: UploadStream, command: UploadJobCommand) -> Job:
        job_id = new_job_id()
        try:
            self._ensure_accepting()
            source_dir = self.store.source_dir(job_id)
            target = source_dir / safe_upload_name(command.filename)
            descriptor, name = tempfile.mkstemp(dir=source_dir, suffix=".upload")
            temporary = Path(name)
            try:
                received = 0
                with os.fdopen(descriptor, "wb") as handle:
                    while chunk := await upload.read(UPLOAD_CHUNK_BYTES):
                        received += len(chunk)
                        if received > self.max_upload_bytes:
                            raise UploadTooLarge()
                        # 写盘放到线程池，阻塞 IO 不占用事件循环。
                        await asyncio.to_thread(handle.write, chunk)
                os.replace(temporary, target)
            except BaseException:
                # 超限、客户端断开或取消时删除临时文件和空任务目录。
                temporary.unlink(missing_ok=True)
                self.store.delete_job_dir(job_id)
                raise
        finally:
            await upload.close()
        title = Path(command.filename.replace("\\", "/")).name or "upload"
        job = replace(Job.new(job_id, str(target), title), options=command.options)
        return self._enqueue(job)

    def list_jobs(self, query: JobQuery) -> JobPage:
        return self.repository.list(query)

    def get_job(self, job_id: str) -> Job:
        try:
            job = self.repository.get(job_id)
        except ValueError:
            # 格式不合法的 ID 与不存在的任务一视同仁，不暴露校验细节。
            job = None
        if job is None:
            raise JobNotFound()
        return job

    def get_result(self, job_id: str) -> JobResult:
        job = self.get_job(job_id)
        if job.status is not JobStatus.SUCCEEDED:
            raise JobNotReady()
        result = self.store.read_result(job_id)
        if result is None:
            raise JobNotReady()
        return result

    def resegment(self, job_id: str, command: ResegmentCommand) -> JobResult:
        with self._artifact_lock:
            job = self.get_job(job_id)
            result = self.get_result(job_id)
            # 按句子顺序展平持久化的词流；不下载、不转码、不调用识别。
            words = [word for sentence in result.sentences for word in sentence.words]
            if not words:
                raise WordsNotAvailable()
            sentences = build_sentences(words, result.duration, command.segmentation)
            updated = replace(result, sentences=sentences, has_clips=False)
            # 旧切片和素材包与新句子不再对应，整体失效。
            shutil.rmtree(self.store.clips_dir(job_id), ignore_errors=True)
            self.store.artifact_path(job_id, "bundle.zip").unlink(missing_ok=True)
            self.exporter.write_text_artifacts(updated)
            self.store.write_result(job_id, updated)
            options = (
                replace(job.options, segmentation=command.segmentation)
                if job.options is not None
                else None
            )
            self.repository.save(
                replace(
                    job,
                    sentence_count=updated.sentence_count,
                    message="已重新切句",
                    options=options,
                    updated_at=datetime.now(UTC),
                )
            )
            return updated

    def delete(self, job_id: str) -> None:
        job = self.get_job(job_id)
        if job.status is JobStatus.RUNNING:
            raise JobRunning()
        self.repository.delete(job_id)
        logger.info("job deleted", extra={"event": "job.deleted", "jobId": job_id})

    def _existing(self, job_id: str, name: str) -> Path:
        path = self.store.artifact_path(job_id, name)
        if not path.is_file():
            raise ArtifactNotFound()
        return path

    def audio_file(self, job_id: str) -> tuple[JobResult, Path]:
        result = self.get_result(job_id)
        return result, self._existing(job_id, result.audio_artifact)

    def subtitle_file(self, job_id: str, fmt: str) -> tuple[JobResult, Path]:
        result = self.get_result(job_id)
        name = SUBTITLE_ARTIFACTS.get(fmt)
        if name is None:
            raise ArtifactNotFound()
        return result, self._existing(job_id, name)

    def clip_file(self, job_id: str, index: int) -> tuple[JobResult, Path]:
        result = self.get_result(job_id)
        if not 0 <= index < len(result.sentences):
            raise SentenceNotFound()
        with self._artifact_lock:
            # 切片按需生成并缓存；与重切句互斥，不会按旧句子边界写出切片。
            return result, self.exporter.ensure_clip(result, index)

    def bundle_file(self, job_id: str, include_clips: bool) -> tuple[JobResult, Path]:
        result = self.get_result(job_id)
        with self._artifact_lock:
            return result, self.exporter.build_bundle(result, include_clips)
