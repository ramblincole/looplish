import json
from dataclasses import replace
from datetime import UTC, datetime
from threading import RLock

from looplish_api.domain.models import Job, JobPage, JobQuery, JobStatus, Problem
from looplish_api.infrastructure.storage.file_artifact_store import FileArtifactStore
from looplish_api.infrastructure.storage.serde import job_from_dict, job_to_dict


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
            jobs = []
            for path in self.store.root.glob("*/job.json"):
                job = job_from_dict(json.loads(path.read_text(encoding="utf-8")))
                if query.status is None or job.status is query.status:
                    jobs.append(job)
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
        cursor = None
        # 分页遍历全部历史任务，不能只恢复第一页。
        while True:
            page = self.list(JobQuery(limit=200, cursor=cursor))
            for job in page.items:
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
            if page.next_cursor is None:
                break
            cursor = page.next_cursor
        return recovered
