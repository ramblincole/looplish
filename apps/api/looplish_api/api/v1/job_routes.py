from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import quote

from fastapi import APIRouter, File, Form, Query, Response, UploadFile, status
from fastapi import Path as PathParam
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse
from pydantic import ValidationError

from looplish_api.api.dependencies import ContainerDep
from looplish_api.api.schemas import (
    CreateJobRequest,
    JobOptionsRequest,
    JobPageResponse,
    JobResponse,
    JobResultResponse,
    ResegmentRequest,
)
from looplish_api.application.commands import (
    CreateJobCommand,
    ResegmentCommand,
    UploadJobCommand,
)
from looplish_api.domain.models import JobQuery, JobStatus

router = APIRouter(prefix="/api/v1/jobs", tags=["jobs"])
FORBIDDEN_IN_FILENAME = set('\\/"\r\n:*?<>|;')
SUBTITLE_TYPES = {
    "srt": "application/x-subrip; charset=utf-8",
    "vtt": "text/vtt; charset=utf-8",
    "txt": "text/plain; charset=utf-8",
}


def download_headers(title: str, extension: str, inline: bool = False) -> dict[str, str]:
    # 文件名只来自清理后的标题：去掉控制字符、引号、路径分隔符和响应头特殊字符。
    base = "".join(
        char for char in title if char.isprintable() and char not in FORBIDDEN_IN_FILENAME
    )
    base = base.strip(" .")[:120] or "looplish"
    name = f"{base}.{extension}"
    fallback = "".join(char if 32 <= ord(char) < 127 else "_" for char in name)
    kind = "inline" if inline else "attachment"
    encoded = quote(name, safe="")
    # ASCII 兼容名给旧客户端，filename* 按 RFC 5987 携带完整的 UTF-8 文件名。
    value = f"{kind}; filename=\"{fallback}\"; filename*=UTF-8''{encoded}"
    return {"Content-Disposition": value}


@router.post("", response_model=JobResponse, status_code=status.HTTP_202_ACCEPTED)
def create_job(body: CreateJobRequest, container: ContainerDep) -> JobResponse:
    # Schema 负责应用配置默认值；Service 负责持久化与入队事务。
    command = CreateJobCommand(body.source, body.to_job_options(container.settings))
    return JobResponse.from_domain(container.service.create_from_source(command))


@router.post("/upload", response_model=JobResponse, status_code=status.HTTP_202_ACCEPTED)
async def upload_job(
    container: ContainerDep,
    file: Annotated[UploadFile, File()],
    asrBackend: Annotated[str | None, Form()] = None,
    subtitleSource: Annotated[str | None, Form()] = None,
    language: Annotated[str | None, Form()] = None,
    makeClips: Annotated[bool | None, Form()] = None,
    minDuration: Annotated[float | None, Form()] = None,
    maxDuration: Annotated[float | None, Form()] = None,
    hardPause: Annotated[float | None, Form()] = None,
    leadPad: Annotated[float | None, Form()] = None,
    tailPad: Annotated[float | None, Form()] = None,
) -> JobResponse:
    fields = {
        "asrBackend": asrBackend,
        "subtitleSource": subtitleSource,
        "language": language,
        "makeClips": makeClips,
        "minDuration": minDuration,
        "maxDuration": maxDuration,
        "hardPause": hardPause,
        "leadPad": leadPad,
        "tailPad": tailPad,
    }
    try:
        # 与 JSON 创建共用同一个参数模型，只把客户端实际提交的字段交给它。
        request = JobOptionsRequest.model_validate(
            {name: value for name, value in fields.items() if value is not None}
        )
        options = request.to_job_options(container.settings)
    except ValidationError as error:
        await file.close()
        raise RequestValidationError(error.errors()) from None
    except Exception:
        await file.close()
        raise
    command = UploadJobCommand(file.filename or "upload", options)
    return JobResponse.from_domain(await container.service.create_from_upload(file, command))


@router.get("", response_model=JobPageResponse)
def list_jobs(
    container: ContainerDep,
    job_status: Annotated[JobStatus | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    cursor: Annotated[str | None, Query(max_length=64)] = None,
) -> JobPageResponse:
    # 分页与状态过滤先转成领域查询，Repository 不暴露给 Router。
    page = container.service.list_jobs(JobQuery(status=job_status, limit=limit, cursor=cursor))
    return JobPageResponse(
        items=[JobResponse.from_domain(item) for item in page.items],
        nextCursor=page.next_cursor,
    )


@router.get("/{job_id}", response_model=JobResponse)
def get_job(job_id: str, container: ContainerDep) -> JobResponse:
    return JobResponse.from_domain(container.service.get_job(job_id))


@router.delete("/{job_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_job(job_id: str, container: ContainerDep) -> Response:
    container.service.delete(job_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{job_id}/result", response_model=JobResultResponse)
def get_result(job_id: str, container: ContainerDep) -> JobResultResponse:
    return JobResultResponse.from_domain(container.service.get_result(job_id))


@router.post("/{job_id}/resegment", response_model=JobResultResponse)
def resegment(job_id: str, body: ResegmentRequest, container: ContainerDep) -> JobResultResponse:
    job = container.service.get_job(job_id)
    current = (
        job.options.segmentation
        if job.options is not None
        else container.settings.default_job_options().segmentation
    )
    # 部分参数与任务当前保存的切句参数合并成完整参数，再交给 Service。
    command = ResegmentCommand(body.merge(current))
    return JobResultResponse.from_domain(container.service.resegment(job_id, command))


@router.get("/{job_id}/audio", response_class=FileResponse)
def get_audio(job_id: str, container: ContainerDep) -> FileResponse:
    result, path = container.service.audio_file(job_id)
    # FileResponse 自带 Range 支持，播放器可以精确拖动。
    return FileResponse(
        path, media_type="audio/mp4", headers=download_headers(result.title, "m4a", inline=True)
    )


@router.get("/{job_id}/subtitles.{fmt}", response_class=FileResponse)
def get_subtitles(
    job_id: str, fmt: Literal["srt", "vtt", "txt"], container: ContainerDep
) -> FileResponse:
    result, path = container.service.subtitle_file(job_id, fmt)
    return FileResponse(
        path, media_type=SUBTITLE_TYPES[fmt], headers=download_headers(result.title, fmt)
    )


@router.get("/{job_id}/clips/{index}", response_class=FileResponse)
def get_clip(
    job_id: str, index: Annotated[int, PathParam(ge=0)], container: ContainerDep
) -> FileResponse:
    result, path = container.service.clip_file(job_id, index)
    return FileResponse(
        path,
        media_type="audio/mpeg",
        headers=download_headers(f"{result.title}-{Path(path).stem}", "mp3"),
    )


@router.get("/{job_id}/bundle.zip", response_class=FileResponse)
def get_bundle(
    job_id: str, container: ContainerDep, clips: Annotated[bool, Query()] = True
) -> FileResponse:
    result, path = container.service.bundle_file(job_id, clips)
    return FileResponse(
        path, media_type="application/zip", headers=download_headers(result.title, "zip")
    )
