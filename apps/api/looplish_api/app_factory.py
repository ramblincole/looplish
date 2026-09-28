from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from looplish_api.api.dependencies import Container
from looplish_api.api.errors import install_error_handlers, install_request_guards
from looplish_api.api.v1.config_routes import router as config_router
from looplish_api.api.v1.health_routes import router as health_router
from looplish_api.api.v1.job_routes import router as job_router
from looplish_api.presentation.static_site import mount_static_site


def create_app(container: Container) -> FastAPI:
    """由已装配的 Container 构造应用；不读环境变量、不创建目录，可安全用于测试和 OpenAPI 导出。"""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        # 启动：先把上次中断的任务收尾，再开始调度新任务。
        container.repository.recover_interrupted()
        container.runner.start()
        try:
            yield
        finally:
            # 关闭：runner.shutdown 先拒绝新任务，再中断排队任务并等待运行中的任务收尾。
            container.runner.shutdown()

    app = FastAPI(title="Looplish API", version="0.1.0", lifespan=lifespan)
    app.state.container = container
    settings = container.settings
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.web_origin],
        allow_credentials=False,
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["Content-Type", "X-Request-Id", "Range"],
        expose_headers=["X-Request-Id", "Content-Disposition", "Content-Range", "Accept-Ranges"],
    )
    install_request_guards(
        app,
        settings.web_origin,
        loopback_only=settings.listens_on_loopback,
        max_upload_bytes=settings.max_upload_bytes,
    )
    install_error_handlers(app)
    app.include_router(health_router)
    app.include_router(config_router)
    app.include_router(job_router)
    # 静态站点最后挂载，只接住所有 API 路由之外的页面请求。
    if settings.web_dist_dir is not None:
        mount_static_site(app, settings.web_dist_dir)
    return app
