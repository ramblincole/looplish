from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from looplish_api.config import Settings
from looplish_api.domain.errors import InvalidJobOptions
from looplish_api.domain.models import (
    Job,
    JobOptions,
    JobResult,
    SegmentationOptions,
    Sentence,
    SubtitleSource,
    Word,
)

AUTO_LANGUAGE = {"", "auto"}


class ApiModel(BaseModel):
    # API 边界拒绝未知字段，并允许显式的驼峰字段名参与构造。
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class ProblemDetails(ApiModel):
    type: str
    title: str
    status: int
    code: str
    detail: str
    requestId: str


class SegmentationRequest(ApiModel):
    minDuration: Annotated[float, Field(ge=0.2, le=10)] = 1.0
    maxDuration: Annotated[float, Field(ge=2, le=60)] = 30.0
    hardPause: Annotated[float, Field(ge=0.1, le=5)] = 0.75
    leadPad: Annotated[float, Field(ge=0, le=2)] = 0.3
    tailPad: Annotated[float, Field(ge=0, le=2)] = 0.4

    @model_validator(mode="after")
    def durations_are_ordered(self) -> "SegmentationRequest":
        if self.minDuration >= self.maxDuration:
            raise ValueError("minDuration must be lower than maxDuration")
        return self


def _segmentation(**values: float | int) -> SegmentationOptions:
    try:
        return SegmentationOptions(**values)  # type: ignore[arg-type]
    except ValueError as error:
        # 部分参数与配置默认值组合后可能不合法（如只传 maxDuration 且小于默认 minDuration）。
        raise InvalidJobOptions(f"切句参数不合法：{error}") from error


class JobOptionsRequest(SegmentationRequest):
    """JSON 创建与 multipart 上传共用的任务参数；两条入口走同一套转换和校验。"""

    asrBackend: str | None = None
    subtitleSource: Literal["auto", "existing", "asr"] = "auto"
    language: str | None = "en"
    makeClips: bool = False

    def to_job_options(self, settings: Settings) -> JobOptions:
        defaults = settings.default_job_options()
        backend = self.asrBackend or defaults.asr_backend
        if backend != settings.asr_backend:
            raise InvalidJobOptions(f"ASR 后端 {backend!r} 未在当前进程中配置。")
        given = self.model_fields_set
        seg = defaults.segmentation
        # model_fields_set 区分“客户端明确传值”和“Schema 默认值”，后者应让配置默认接管。
        language = self.language if "language" in given else defaults.language
        return JobOptions(
            asr_backend=backend,
            asr_model=defaults.asr_model,
            language=None if language is None or language.strip() in AUTO_LANGUAGE else language,
            subtitle_source=(
                SubtitleSource(self.subtitleSource)
                if "subtitleSource" in given
                else defaults.subtitle_source
            ),
            subtitle_languages=defaults.subtitle_languages,
            make_clips=self.makeClips,
            segmentation=_segmentation(
                min_duration=self.minDuration if "minDuration" in given else seg.min_duration,
                max_duration=self.maxDuration if "maxDuration" in given else seg.max_duration,
                hard_pause=self.hardPause if "hardPause" in given else seg.hard_pause,
                lead_pad=self.leadPad if "leadPad" in given else seg.lead_pad,
                tail_pad=self.tailPad if "tailPad" in given else seg.tail_pad,
                min_words=seg.min_words,
            ),
        )


class CreateJobRequest(JobOptionsRequest):
    source: Annotated[str, Field(min_length=1, max_length=4096)]


class ResegmentRequest(ApiModel):
    minDuration: Annotated[float | None, Field(ge=0.2, le=10)] = None
    maxDuration: Annotated[float | None, Field(ge=2, le=60)] = None
    hardPause: Annotated[float | None, Field(ge=0.1, le=5)] = None
    leadPad: Annotated[float | None, Field(ge=0, le=2)] = None
    tailPad: Annotated[float | None, Field(ge=0, le=2)] = None

    @model_validator(mode="after")
    def at_least_one(self) -> "ResegmentRequest":
        if all(value is None for value in self.model_dump().values()):
            raise ValueError("at least one segmentation parameter is required")
        return self

    def merge(self, current: SegmentationOptions) -> SegmentationOptions:
        # 只覆盖客户端给出的参数，其余沿用任务当前保存的切句参数。
        return _segmentation(
            min_duration=current.min_duration if self.minDuration is None else self.minDuration,
            max_duration=current.max_duration if self.maxDuration is None else self.maxDuration,
            hard_pause=current.hard_pause if self.hardPause is None else self.hardPause,
            lead_pad=current.lead_pad if self.leadPad is None else self.leadPad,
            tail_pad=current.tail_pad if self.tailPad is None else self.tailPad,
            min_words=current.min_words,
        )


class ErrorResponse(ApiModel):
    code: str
    detail: str


class JobResponse(ApiModel):
    id: str
    source: str
    title: str
    status: Literal["queued", "running", "succeeded", "failed"]
    stage: Literal["downloading", "preparingAudio", "transcribing", "segmenting"] | None
    progress: float
    message: str
    error: ErrorResponse | None
    createdAt: datetime
    updatedAt: datetime
    sentenceCount: int

    @classmethod
    def from_domain(cls, job: Job) -> "JobResponse":
        return cls(
            id=job.id,
            # 本机源文件只返回显示标题，绝对路径不能穿过 HTTP 边界。
            source=job.source if job.source.startswith(("http://", "https://")) else job.title,
            title=job.title,
            status=job.status.value,
            stage=job.stage.value if job.stage else None,
            progress=job.progress,
            message=job.message,
            error=ErrorResponse(code=job.error.code, detail=job.error.detail)
            if job.error
            else None,
            createdAt=job.created_at,
            updatedAt=job.updated_at,
            sentenceCount=job.sentence_count,
        )


class JobPageResponse(ApiModel):
    items: list[JobResponse]
    nextCursor: str | None


class WordResponse(ApiModel):
    start: float
    end: float
    text: str
    probability: float | None

    @classmethod
    def from_domain(cls, word: Word) -> "WordResponse":
        return cls(start=word.start, end=word.end, text=word.text, probability=word.probability)


class SentenceResponse(ApiModel):
    index: int
    start: float
    end: float
    speechStart: float
    speechEnd: float
    duration: float
    text: str
    words: list[WordResponse]

    @classmethod
    def from_domain(cls, value: Sentence) -> "SentenceResponse":
        return cls(
            index=value.index,
            start=value.start,
            end=value.end,
            speechStart=value.speech_start,
            speechEnd=value.speech_end,
            duration=value.duration,
            text=value.text,
            words=[WordResponse.from_domain(word) for word in value.words],
        )


class JobResultResponse(ApiModel):
    jobId: str
    title: str
    sourceUrl: str | None
    uploader: str | None
    thumbnailUrl: str | None
    duration: float
    language: str | None
    transcriptSource: str
    audioUrl: str
    createdAt: datetime
    sentenceCount: int
    hasClips: bool
    sentences: list[SentenceResponse]

    @classmethod
    def from_domain(cls, value: JobResult) -> "JobResultResponse":
        return cls(
            jobId=value.job_id,
            title=value.title,
            sourceUrl=value.source_url,
            uploader=value.uploader,
            thumbnailUrl=value.thumbnail_url,
            duration=value.duration,
            language=value.language,
            transcriptSource=value.transcript_source,
            audioUrl=f"/api/v1/jobs/{value.job_id}/audio",
            createdAt=value.created_at,
            sentenceCount=value.sentence_count,
            hasClips=value.has_clips,
            sentences=[SentenceResponse.from_domain(item) for item in value.sentences],
        )


class ConfigDefaultsResponse(ApiModel):
    asrBackend: str
    asrModel: str
    language: str | None
    subtitleSource: Literal["auto", "existing", "asr"]
    minDuration: float
    maxDuration: float
    hardPause: float
    leadPad: float
    tailPad: float


class ConfigResponse(ApiModel):
    asrBackends: list[str]
    # 前端据此决定是否显示「本机文件路径」输入。
    allowLocalPaths: bool
    defaults: ConfigDefaultsResponse


# 所有 4xx/5xx 都以 Problem Details 返回；路由据此把错误结构写进 OpenAPI 契约。
PROBLEM_RESPONSES: dict[int | str, dict[str, object]] = {
    "4XX": {"model": ProblemDetails, "description": "Problem Details"},
    "5XX": {"model": ProblemDetails, "description": "Problem Details"},
}
