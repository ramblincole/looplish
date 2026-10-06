import importlib.util
import os
import platform
import sys

from openai import OpenAI

from looplish_api.config import Settings
from looplish_api.domain.ports import MediaProcessor, TranscriptionBackend
from looplish_api.infrastructure.asr.fake_backend import FakeTranscriptionBackend
from looplish_api.infrastructure.asr.local_backend import LocalWhisperBackend
from looplish_api.infrastructure.asr.mlx_backend import MlxWhisperBackend, mlx_repo
from looplish_api.infrastructure.asr.openai_backend import (
    ChunkedCloudBackend,
    OpenAICompatibleBackend,
)

GROQ_BASE_URL = "https://api.groq.com/openai/v1"
DEFAULT_CLOUD_MODELS = {"openai": "whisper-1", "groq": "whisper-large-v3-turbo"}


def default_cpu_threads() -> int:
    # 实测 15 核 Apple 芯片上 10 线程最快，再多反而争抢；不少于 CTranslate2 的默认 4 线程。
    cores = os.process_cpu_count() or 4
    return max(4, min(12, cores * 2 // 3))


def mlx_available() -> bool:
    return (
        sys.platform == "darwin"
        and platform.machine() == "arm64"
        and importlib.util.find_spec("mlx_whisper") is not None
    )


def build_local_backend(settings: Settings) -> TranscriptionBackend:
    repo_id = mlx_repo(settings.asr_model)
    use_mlx = settings.asr_engine == "mlx" or (
        settings.asr_engine == "auto" and repo_id is not None and mlx_available()
    )
    if use_mlx:
        if repo_id is None:
            raise ValueError(f"no MLX weights for ASR model: {settings.asr_model}")
        return MlxWhisperBackend(settings.asr_model, repo_id, settings.models_dir)
    return LocalWhisperBackend(
        settings.asr_model,
        settings.models_dir,
        settings.asr_device,
        settings.asr_compute_type,
        cpu_threads=settings.asr_cpu_threads or default_cpu_threads(),
        batch_size=settings.asr_batch_size,
    )


def build_backend(settings: Settings, media: MediaProcessor) -> TranscriptionBackend:
    # Fake 与 local 不需要 API Key；local 模型仍由后端在首次识别时加载。
    if settings.asr_backend == "fake":
        return FakeTranscriptionBackend()
    if settings.asr_backend == "local":
        return build_local_backend(settings)
    if settings.asr_backend not in DEFAULT_CLOUD_MODELS:
        raise ValueError(f"unknown ASR backend: {settings.asr_backend}")
    # SecretStr 只在构造 SDK 客户端时解包，不进入后端 repr 或错误消息。
    key = settings.asr_api_key
    if key is None:
        raise ValueError("cloud ASR backend requires API key")
    base_url = settings.asr_base_url
    if settings.asr_backend == "groq" and base_url is None:
        base_url = GROQ_BASE_URL
    client = OpenAI(
        api_key=key.get_secret_value(),
        base_url=base_url,
        max_retries=3,
        timeout=120.0,
    )
    model = settings.asr_api_model or DEFAULT_CLOUD_MODELS[settings.asr_backend]
    delegate = OpenAICompatibleBackend(settings.asr_backend, client, model, 25_000_000)
    # 包装器阈值留出 1 MB 余量，delegate 再执行最终硬限制。
    return ChunkedCloudBackend(delegate, media, 24_000_000)
