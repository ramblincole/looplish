from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from threading import Lock
from time import monotonic_ns

from looplish_api.domain.models import JobStage, JobStatus
from looplish_api.domain.ports import JobRepository

# 设计第 7.1 节的建议权重；未执行的阶段不传入，自然不占权重。
DOWNLOAD_WEIGHT = 10.0
PREPARE_WEIGHT = 15.0
TRANSCRIBE_WEIGHT = 60.0
SEGMENT_WEIGHT = 15.0


@dataclass(frozen=True)
class StageWeight:
    stage: JobStage
    weight: float


def pipeline_stages(downloads: bool) -> tuple[StageWeight, ...]:
    stages = (
        StageWeight(JobStage.PREPARING_AUDIO, PREPARE_WEIGHT),
        StageWeight(JobStage.TRANSCRIBING, TRANSCRIBE_WEIGHT),
        StageWeight(JobStage.SEGMENTING, SEGMENT_WEIGHT),
    )
    # 上传和本机文件跳过下载，下载阶段不占权重。
    return ((StageWeight(JobStage.DOWNLOADING, DOWNLOAD_WEIGHT),) if downloads else ()) + stages


class ProgressReporter:
    def __init__(
        self,
        stages: tuple[StageWeight, ...],
        sink: Callable[[JobStage, float, str], None],
    ) -> None:
        # 构造时拒绝无法归一化的配置，避免任务运行中才出现除零或负进度。
        if not stages or any(item.weight <= 0 for item in stages):
            raise ValueError("progress stages require positive weights")
        total = sum(item.weight for item in stages)
        self.stages = stages
        self.weights = {item.stage: item.weight / total for item in stages}
        self.sink = sink
        self.last = 0.0

    def report(self, stage: JobStage, local: float, message: str) -> None:
        if stage not in self.weights:
            raise ValueError(f"unknown progress stage: {stage}")
        before = 0.0
        for item in self.stages:
            if item.stage is stage:
                break
            before += self.weights[item.stage]
        # 先限制阶段值，再与历史最大值合并，避免顺序回调让进度倒退；线程安全由外层 sink 负责。
        value = min(1.0, before + self.weights[stage] * max(0.0, min(1.0, local)))
        self.last = max(self.last, value)
        self.sink(stage, self.last, message)


class ThrottledProgressSink:
    """把全局进度写入 job.json；同一阶段内的更新最多每 200 ms 落盘一次。"""

    def __init__(
        self,
        repository: JobRepository,
        interval_ns: int = 200_000_000,
        clock: Callable[[], int] = monotonic_ns,
    ) -> None:
        self.repository = repository
        self.interval_ns = interval_ns
        self.clock = clock
        self._last: dict[str, tuple[int, JobStage]] = {}
        self._lock = Lock()

    def __call__(self, job_id: str, stage: JobStage, progress: float, message: str) -> None:
        now = self.clock()
        with self._lock:
            last = self._last.get(job_id)
            # 进入新阶段总是立即落盘；同阶段内过密的更新直接丢弃，下一次写入会带上更新后的值。
            if last is not None and last[1] is stage and now - last[0] < self.interval_ns:
                return
            self._last[job_id] = (now, stage)
        job = self.repository.get(job_id)
        # 只更新运行中的任务，终态由 Runner 负责写入。
        if job is None or job.status is not JobStatus.RUNNING:
            return
        self.repository.save(
            replace(
                job,
                stage=stage,
                progress=progress,
                message=message,
                updated_at=datetime.now(UTC),
            )
        )
