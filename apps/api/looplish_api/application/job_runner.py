import logging
from concurrent.futures import Future, ThreadPoolExecutor, wait
from datetime import UTC, datetime
from queue import Empty, Full, Queue
from threading import BoundedSemaphore, Event, Lock, Thread
from time import monotonic

from looplish_api.application.processing_pipeline import ProcessingPipeline
from looplish_api.domain.errors import DomainError, QueueFull, ServiceStopping
from looplish_api.domain.models import JobStatus, Problem

logger = logging.getLogger(__name__)
POLL_SECONDS = 0.1
INTERRUPTED = Problem("JOB_INTERRUPTED", "服务停止导致任务中断。")
INTERNAL = Problem("INTERNAL_ERROR", "任务处理失败。")


class JobRunner:
    def __init__(
        self,
        pipeline: ProcessingPipeline,
        max_workers: int = 1,
        queue_size: int = 32,
    ) -> None:
        self.pipeline = pipeline
        self.repository = pipeline.repository
        self.queue: Queue[str] = Queue(maxsize=queue_size)
        self.executor = ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix="looplish-job"
        )
        self.futures: set[Future[None]] = set()
        self.lock = Lock()
        # 提交和关闭互斥：一旦开始关闭，就不会再有任务漏进队列而无人处理。
        self.submit_lock = Lock()
        self.slots = BoundedSemaphore(max_workers)
        self.stopping = Event()
        self.dispatcher = Thread(target=self._dispatch, name="looplish-dispatcher", daemon=True)

    def start(self) -> None:
        if not self.dispatcher.is_alive():
            self.dispatcher.start()

    def submit(self, job_id: str) -> None:
        with self.submit_lock:
            if self.stopping.is_set():
                raise ServiceStopping()
            try:
                self.queue.put_nowait(job_id)
            except Full as error:
                raise QueueFull() from error

    def _dispatch(self) -> None:
        while not self.stopping.is_set():
            # 先取得 worker 槽位再取队列项，等待中的任务一直留在有界队列里，容量才可见。
            if not self.slots.acquire(timeout=POLL_SECONDS):
                continue
            try:
                job_id = self.queue.get(timeout=POLL_SECONDS)
            except Empty:
                self.slots.release()
                continue
            if self.stopping.is_set():
                # 关闭信号已发出，这个任务不再启动。
                self.slots.release()
                self._interrupt(job_id)
                return
            future = self.executor.submit(self._run_one, job_id)
            with self.lock:
                self.futures.add(future)
            future.add_done_callback(self._finished)

    def _finished(self, future: Future[None]) -> None:
        try:
            # 显式读取异常，避免 Future 中的未观察异常悄然丢失。
            if future.exception() is not None:
                logger.error("job worker crashed", extra={"event": "job.worker_crashed"})
        finally:
            with self.lock:
                self.futures.discard(future)
            self.slots.release()

    def _run_one(self, job_id: str) -> None:
        job = self.repository.get(job_id)
        # 任务已被删除，或在排队期间被标记为中断时直接跳过。
        if job is None or job.status is not JobStatus.QUEUED:
            return
        started = monotonic()
        self.repository.save(
            job.transition(JobStatus.RUNNING, datetime.now(UTC), message="开始处理")
        )
        logger.info("job started", extra={"event": "job.started", "jobId": job_id})
        try:
            result = self.pipeline.run(job_id)
        except Exception as error:
            # 领域异常保留稳定 code/detail，未知异常收敛为不泄露内部信息的通用错误。
            problem = (
                Problem(error.code, error.detail) if isinstance(error, DomainError) else INTERNAL
            )
            self._finish(job_id, JobStatus.FAILED, message="处理失败", error=problem)
            logger.warning(
                "job failed",
                extra={
                    "event": "job.failed",
                    "jobId": job_id,
                    "errorCode": problem.code,
                    "durationMs": round((monotonic() - started) * 1000),
                },
            )
            return
        self._finish(
            job_id,
            JobStatus.SUCCEEDED,
            progress=1.0,
            message="处理完成",
            sentence_count=result.sentence_count,
        )
        logger.info(
            "job succeeded",
            extra={
                "event": "job.succeeded",
                "jobId": job_id,
                "durationMs": round((monotonic() - started) * 1000),
            },
        )

    def _finish(
        self,
        job_id: str,
        status: JobStatus,
        *,
        message: str,
        progress: float | None = None,
        error: Problem | None = None,
        sentence_count: int | None = None,
    ) -> None:
        # 以磁盘上的最新状态为基础，保留流水线写入的进度；stage 在终态清空。
        current = self.repository.get(job_id)
        if current is None:
            return
        finished = current.transition(
            status,
            datetime.now(UTC),
            stage=None,
            message=message,
            error=error,
            progress=current.progress if progress is None else progress,
            sentence_count=current.sentence_count if sentence_count is None else sentence_count,
        )
        self.repository.save(finished)

    def _interrupt(self, job_id: str) -> None:
        job = self.repository.get(job_id)
        if job is None or job.status is not JobStatus.QUEUED:
            return
        self.repository.save(
            job.transition(
                JobStatus.FAILED,
                datetime.now(UTC),
                message="服务停止导致任务中断",
                error=INTERRUPTED,
            )
        )
        logger.info(
            "job interrupted",
            extra={"event": "job.interrupted", "jobId": job_id, "errorCode": INTERRUPTED.code},
        )

    def shutdown(self, grace_seconds: float = 30.0) -> None:
        # 先拒绝新任务并停止调度，再把尚未开始的任务标为中断。
        with self.submit_lock:
            self.stopping.set()
        if self.dispatcher.is_alive():
            self.dispatcher.join(timeout=grace_seconds)
        while True:
            try:
                self._interrupt(self.queue.get_nowait())
            except Empty:
                break
        # 已开始的任务在宽限期内正常收尾；这里不预先标记 failed，避免覆盖迟到的 succeeded。
        with self.lock:
            pending = tuple(self.futures)
        wait(pending, timeout=grace_seconds)
        self.executor.shutdown(wait=False, cancel_futures=True)
