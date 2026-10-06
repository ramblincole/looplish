# 一个镜像跑完整个应用：先构建前端，再由后端托管页面（单端口 8756）。

# ---- 前端构建 ----
FROM node:24-slim AS web
WORKDIR /src
RUN corepack enable
# 先只拷依赖清单，源码变动时可以复用依赖层的缓存。
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
COPY apps/web/package.json apps/web/
COPY packages/contracts/package.json packages/contracts/
RUN pnpm install --frozen-lockfile --filter @looplish/web...
COPY apps/web apps/web
COPY packages/contracts packages/contracts
RUN pnpm --dir apps/web build

# ---- 运行时 ----
FROM python:3.13-slim
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH=/opt/venv/bin:$PATH

WORKDIR /app
COPY apps/api/pyproject.toml apps/api/uv.lock ./
RUN uv sync --frozen --no-dev --extra local-asr --no-install-project
COPY apps/api/looplish_api looplish_api
RUN uv sync --frozen --no-dev --extra local-asr --no-editable
COPY --from=web /src/apps/web/dist /app/web

# 以普通用户运行；预先建好 /data，具名卷首次挂载时会继承这里的属主。
RUN useradd --create-home --uid 1000 looplish \
    && mkdir -p /data/jobs /data/models /data/logs \
    && chown -R looplish:looplish /data
USER looplish

# 容器内监听所有地址，宿主机端口的暴露范围由 docker-compose.yml 决定。
ENV LOOPLISH_HOST=0.0.0.0 \
    LOOPLISH_PORT=8756 \
    LOOPLISH_ENV_FILE= \
    LOOPLISH_WEB_DIST_DIR=/app/web \
    LOOPLISH_DATA_DIR=/data/jobs \
    LOOPLISH_MODELS_DIR=/data/models \
    LOOPLISH_LOG_DIR=/data/logs

VOLUME ["/data"]
EXPOSE 8756
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8756/health/live')"

CMD ["uvicorn", "looplish_api.main:app", "--host", "0.0.0.0", "--port", "8756"]
