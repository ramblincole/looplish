import importlib.util
import os
import shutil
import tempfile
from collections.abc import Callable
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from looplish_api.api.dependencies import ContainerDep
from looplish_api.config import Settings

router = APIRouter(tags=["health"])


@router.get("/health/live")
def live() -> dict[str, str]:
    return {"status": "ok"}


def _writable(directory: Path) -> bool:
    try:
        directory.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryFile(dir=directory):
            return True
    except OSError:
        return False


def _executable(command: str) -> bool:
    path = Path(command)
    if path.is_file():
        return os.access(path, os.X_OK)
    return shutil.which(command) is not None


def _asr_ready(settings: Settings) -> bool:
    # 只检查本地依赖与配置，不访问网络、不下载模型。
    if settings.asr_backend == "local":
        return importlib.util.find_spec("faster_whisper") is not None
    if settings.asr_backend in {"openai", "groq"}:
        key = settings.asr_api_key
        return key is not None and bool(key.get_secret_value().strip())
    return settings.asr_backend == "fake"


def failed_components(settings: Settings) -> list[str]:
    checks: dict[str, Callable[[], bool]] = {
        "dataDir": lambda: _writable(settings.data_dir),
        "logDir": lambda: _writable(settings.log_dir),
        "modelsDir": lambda: settings.asr_backend != "local" or _writable(settings.models_dir),
        "ffmpeg": lambda: _executable(settings.ffmpeg_path),
        "ffprobe": lambda: _executable(settings.ffprobe_path),
        "webDist": lambda: (
            settings.web_dist_dir is None or (settings.web_dist_dir / "index.html").is_file()
        ),
        "asrBackend": lambda: _asr_ready(settings),
    }
    return [name for name, check in checks.items() if not check()]


@router.get("/health/ready", response_model=None)
def ready(container: ContainerDep) -> dict[str, str] | JSONResponse:
    failed = failed_components(container.settings)
    if failed:
        # 只返回组件名，不返回路径、Key 或底层异常。
        return JSONResponse({"status": "unavailable", "failed": failed}, status_code=503)
    return {"status": "ok"}
