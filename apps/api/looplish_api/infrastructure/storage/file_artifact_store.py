import json
import os
import re
import shutil
import tempfile
from pathlib import Path
from typing import Any

from looplish_api.domain.models import JobResult
from looplish_api.infrastructure.storage.path_safety import ensure_within
from looplish_api.infrastructure.storage.serde import job_result_from_dict, job_result_to_dict

JOB_ID = re.compile(r"^[A-Z0-9]{12,26}$")
ALLOWED_ARTIFACTS = {
    "job.json",
    "result.json",
    "audio.m4a",
    "asr-input.wav",
    "asr-upload.mp3",
    "subtitles.srt",
    "subtitles.vtt",
    "sentences.txt",
    "anki_import.tsv",
    "bundle.zip",
}


class FileArtifactStore:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def job_dir(self, job_id: str) -> Path:
        if JOB_ID.fullmatch(job_id) is None:
            raise ValueError("invalid job id")
        return ensure_within(self.root, self.root / job_id)

    def source_dir(self, job_id: str) -> Path:
        target = ensure_within(self.job_dir(job_id), self.job_dir(job_id) / "source")
        target.mkdir(parents=True, exist_ok=True)
        return target

    def clips_dir(self, job_id: str) -> Path:
        target = ensure_within(self.job_dir(job_id), self.job_dir(job_id) / "clips")
        target.mkdir(parents=True, exist_ok=True)
        return target

    def artifact_path(self, job_id: str, name: str) -> Path:
        if name not in ALLOWED_ARTIFACTS:
            raise ValueError("unknown artifact name")
        return ensure_within(self.job_dir(job_id), self.job_dir(job_id) / name)

    def atomic_json(self, path: Path, value: dict[str, Any]) -> None:
        path = ensure_within(self.root, path)
        path.parent.mkdir(parents=True, exist_ok=True)
        # 临时文件必须与目标同目录，os.replace 才能保持同文件系统原子替换。
        descriptor, temporary_name = tempfile.mkstemp(
            dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
                json.dump(value, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
                handle.flush()
                # 先把内容刷到磁盘，再替换正式文件，避免崩溃留下半截 JSON。
                os.fsync(handle.fileno())
            os.replace(temporary_name, path)
        finally:
            # replace 成功后路径已消失；失败时仍清理残留临时文件。
            temporary = Path(temporary_name)
            if temporary.exists():
                temporary.unlink()

    def write_result(self, job_id: str, result: JobResult) -> None:
        self.atomic_json(self.artifact_path(job_id, "result.json"), job_result_to_dict(result))

    def read_result(self, job_id: str) -> JobResult | None:
        path = self.artifact_path(job_id, "result.json")
        if not path.exists():
            return None
        return job_result_from_dict(json.loads(path.read_text(encoding="utf-8")))

    def delete_job_dir(self, job_id: str) -> None:
        target = self.job_dir(job_id)
        if target.parent != self.root:
            raise ValueError("job directory must be a direct child of data root")
        shutil.rmtree(target)
