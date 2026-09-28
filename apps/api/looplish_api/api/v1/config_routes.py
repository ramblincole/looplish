from fastapi import APIRouter

from looplish_api.api.dependencies import ContainerDep
from looplish_api.api.schemas import PROBLEM_RESPONSES, ConfigDefaultsResponse, ConfigResponse

router = APIRouter(prefix="/api/v1", tags=["config"], responses=PROBLEM_RESPONSES)


@router.get("/config", response_model=ConfigResponse)
def get_config(container: ContainerDep) -> ConfigResponse:
    settings = container.settings
    defaults = settings.default_job_options()
    seg = defaults.segmentation
    # 可用后端来自当前实际装配，不宣告未配置凭据的供应商。
    return ConfigResponse(
        asrBackends=[settings.asr_backend],
        allowLocalPaths=settings.local_paths_enabled,
        defaults=ConfigDefaultsResponse(
            asrBackend=defaults.asr_backend,
            asrModel=defaults.asr_model,
            language=defaults.language,
            subtitleSource=defaults.subtitle_source.value,
            minDuration=seg.min_duration,
            maxDuration=seg.max_duration,
            hardPause=seg.hard_pause,
            leadPad=seg.lead_pad,
            tailPad=seg.tail_pad,
        ),
    )
