from fastapi import FastAPI

from looplish_api.api.dependencies import Container, build_container
from looplish_api.app_factory import create_app as build_app
from looplish_api.config import Settings
from looplish_api.logging import configure_logging


def create_app(container: Container | None = None) -> FastAPI:
    # 运行入口：缺少 Container 时按进程环境装配；测试和 OpenAPI 导出应直接用 app_factory。
    if container is None:
        settings = Settings.from_environment()
        configure_logging(settings.log_dir)
        container = build_container(settings)
    return build_app(container)


app = create_app()
