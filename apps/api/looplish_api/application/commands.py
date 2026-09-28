from dataclasses import dataclass
from typing import Protocol

from looplish_api.domain.models import JobOptions, SegmentationOptions


@dataclass(frozen=True, slots=True)
class CreateJobCommand:
    source: str
    options: JobOptions


@dataclass(frozen=True, slots=True)
class UploadJobCommand:
    filename: str
    options: JobOptions


@dataclass(frozen=True, slots=True)
class ResegmentCommand:
    segmentation: SegmentationOptions


class UploadStream(Protocol):
    # FastAPI 的 UploadFile 满足此协议；应用层不依赖 Web 框架类型。
    async def read(self, size: int = -1) -> bytes: ...
    async def close(self) -> None: ...
