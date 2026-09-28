import json
import logging
from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, datetime
from threading import RLock

from looplish_api.domain.models import Job, JobPage, JobQuery, JobStatus, Problem
from looplish_api.infrastructure.storage.file_artifact_store import FileArtifactStore
from looplish_api.infrastructure.storage.serde import job_from_dict, job_to_dict

logger = logging.getLogger(__name__)


class JsonJobRepository:
    def __init__(self, store: FileArtifactStore) -> None:
        self.store = store
        self._lock = RLock()

    def save(self, job: Job) -> None:
        with self._lock:
            self.store.atomic_json(self.store.artifact_path(job.id, "job.json"), job_to_dict(job))

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            path = self.store.artifact_path(job_id, "job.json")
            if not path.exists():
                return None
            return job_from_dict(json.loads(path.read_text(encoding="utf-8")))

    def list(self, query: JobQuery) -> JobPage:
        with self._lock:
            jobs = [
                job
                for job in self._load_all()
                if query.status is None or job.status is query.status
            ]
            # 用 id 作为同时间戳的稳定次级排序键，确保 cursor 翻页可重现。
            jobs.sort(key=lambda item: (item.created_at, item.id), reverse=True)
            if query.cursor:
                cursor_index = next(
                    (index for index, item in enumerate(jobs) if item.id == query.cursor),
                    None,
                )
                jobs = jobs[cursor_index + 1 :] if cursor_index is not None else []
            page = jobs[: query.limit]
            next_cursor = page[-1].id if len(jobs) > query.limit else None
            return JobPage(tuple(page), next_cursor)

    def delete(self, job_id: str) -> bool:
        with self._lock:
            job = self.get(job_id)
            if job is None:
                return False
            self.store.delete_job_dir(job_id)
            return True

    def recover_interrupted(self) -> int:
        recovered = 0
        with self._lock:
            # 一次遍历全部任务文件；借用分页会让每页都重读整个目录。
            for job in tuple(self._load_all()):
                if job.status not in {JobStatus.QUEUED, JobStatus.RUNNING}:
                    continue
                failed = replace(
                    job,
                    status=JobStatus.FAILED,
                    stage=None,
                    message="服务重启导致任务中断",
                    error=Problem("JOB_INTERRUPTED", "服务重启导致任务中断。"),
                    updated_at=datetime.now(UTC),
                )
                self.save(failed)
                recovered += 1
        return recovered

    def _load_all(self) -> Iterator[Job]:
        for path in self.store.root.glob("*/job.json"):
            try:
                yield job_from_dict(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
                # 单个坏文件不能拖垮列表和启动恢复；跳过并留下排查线索。
                logger.warning("skipping unreadable job file %s: %s", path, error)
