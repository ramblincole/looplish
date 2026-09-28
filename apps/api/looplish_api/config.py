import os
from pathlib import Path
from shutil import which
from typing import Self

from platformdirs import user_cache_path, user_data_path, user_log_path
from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from looplish_api.domain.models import JobOptions, SegmentationOptions, SubtitleSource


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="LOOPLISH_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        frozen=True,
    )

    host: str = "127.0.0.1"
    port: int = Field(default=8756, ge=1, le=65535)
    web_origin: str = "http://127.0.0.1:5173"
    web_dist_dir: Path | None = None
    data_dir: Path = Field(default_factory=lambda: user_data_path("Looplish") / "jobs")
    models_dir: Path = Field(default_factory=lambda: user_cache_path("Looplish") / "models")
    log_dir: Path = Field(default_factory=lambda: user_log_path("Looplish"))
    ffmpeg_path: str = Field(default_factory=lambda: which("ffmpeg") or "ffmpeg")
    ffprobe_path: str = Field(default_factory=lambda: which("ffprobe") or "ffprobe")
    max_workers: int = Field(default=1, ge=1, le=4)
    max_upload_bytes: int = Field(default=2_147_483_648, ge=1)
    max_download_bytes: int = Field(default=2_147_483_648, ge=1)
    max_media_seconds: float = Field(default=14_400, gt=0)
    asr_backend: str = "local"
    asr_model: str = "small.en"
    language: str = "en"
    asr_device: str = "auto"
    asr_compute_type: str = "int8"
    asr_api_key: SecretStr | None = Field(default=None, repr=False)
    asr_base_url: str | None = None
    asr_api_model: str | None = None
    subtitle_source: SubtitleSource = SubtitleSource.AUTO
    subtitle_languages: str = "en,en-US,en-GB"
    seg_min_seconds: float = 1.0
    seg_max_seconds: float = 14.0
    seg_hard_pause_seconds: float = 0.75
    seg_lead_pad_seconds: float = 0.20
    seg_tail_pad_seconds: float = 0.40

    @classmethod
    def from_environment(cls) -> Self:
        # 空字符串显式关闭 dotenv，便于服务部署只信任进程环境。
        env_file = os.environ.get("LOOPLISH_ENV_FILE", ".env").strip()
        return cls(_env_file=env_file or None)

    @model_validator(mode="after")
    def validate_runtime(self) -> "Settings":
        # 启动时一次性验证后端和派生切句参数，避免任务运行到中途才失败。
        if self.asr_backend not in {"local", "openai", "groq", "fake"}:
            raise ValueError(f"unknown ASR backend: {self.asr_backend}")
        if self.asr_backend in {"openai", "groq"} and self.asr_api_key is None:
            raise ValueError("cloud ASR backend requires an API key")
        self.segmentation()
        return self

    def segmentation(self) -> SegmentationOptions:
        return SegmentationOptions(
            min_duration=self.seg_min_seconds,
            max_duration=self.seg_max_seconds,
            hard_pause=self.seg_hard_pause_seconds,
            lead_pad=self.seg_lead_pad_seconds,
            tail_pad=self.seg_tail_pad_seconds,
        )

    def default_job_options(self) -> JobOptions:
        languages = tuple(
            value.strip() for value in self.subtitle_languages.split(",") if value.strip()
        )
        return JobOptions(
            asr_backend=self.asr_backend,
            asr_model=self.asr_model,
            language=self.language or None,
            subtitle_source=self.subtitle_source,
            subtitle_languages=languages,
            make_clips=False,
            segmentation=self.segmentation(),
        )
