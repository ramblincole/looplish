import logging
import re
from collections.abc import Awaitable, Callable
from urllib.parse import urlsplit
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from starlette.exceptions import HTTPException as StarletteHTTPException

from looplish_api.domain.errors import DomainError

REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "[::1]", "::1"}
HTTP_CODES = {404: "NOT_FOUND", 405: "METHOD_NOT_ALLOWED", 413: "PAYLOAD_TOO_LARGE"}

logger = logging.getLogger(__name__)
CallNext = Callable[[Request], Awaitable[Response]]


def request_id(request: Request) -> str:
    return getattr(request.state, "request_id", None) or f"req_{uuid4().hex}"


def problem(request: Request, status: int, code: str, detail: str) -> JSONResponse:
    # 响应只使用稳定字段，不序列化异常对象、堆栈或内部路径。
    rid = request_id(request)
    body = {
        "type": f"https://looplish.dev/problems/{code.lower().replace('_', '-')}",
        "title": code.replace("_", " ").title(),
        "status": status,
        "code": code,
        "detail": detail,
        "requestId": rid,
    }
    return JSONResponse(
        body,
        status_code=status,
        media_type="application/problem+json",
        headers={"X-Request-Id": rid},
    )


def _host_name(value: str) -> str:
    return (urlsplit(f"//{value}").hostname or "").lower()


def install_request_guards(
    app: FastAPI, web_origin: str, loopback_only: bool, max_upload_bytes: int
) -> None:
    allowed_origin = web_origin.rstrip("/").lower()
    allowed_hosts = LOOPBACK_HOSTS | {_host_name(urlsplit(web_origin).netloc)}

    @app.middleware("http")
    async def guard(request: Request, call_next: CallNext) -> Response:
        host = _host_name(request.headers.get("host", ""))
        # 只监听本机时校验 Host，防止恶意域名经 DNS 重绑定指向 127.0.0.1 后读写本机 API。
        if loopback_only and host not in allowed_hosts:
            return problem(request, 403, "HOST_NOT_ALLOWED", "请求的主机名不被允许。")
        origin = request.headers.get("origin")
        if request.method in UNSAFE_METHODS and origin is not None:
            origin = origin.rstrip("/").lower()
            # 本机静态站点与 API 同源：Origin 的主机和端口与请求的 Host 完全一致。
            same_origin = urlsplit(origin).netloc == request.headers.get("host", "").lower()
            # multipart 上传属于浏览器「简单请求」，不经 CORS 预检；其他网站发起的写操作一律拒绝。
            if origin != allowed_origin and not same_origin:
                return problem(request, 403, "ORIGIN_NOT_ALLOWED", "不接受来自该来源的请求。")
        if request.url.path == "/api/v1/jobs/upload" and request.method == "POST":
            length = request.headers.get("content-length")
            # 声明的请求体已明显超限时，在框架把整个上传缓存到临时文件之前就拒绝。
            if (
                length is not None
                and length.isdigit()
                and int(length) > max_upload_bytes + 1_048_576
            ):
                return problem(request, 413, "UPLOAD_TOO_LARGE", "上传文件超过大小上限。")
        return await call_next(request)


def install_error_handlers(app: FastAPI) -> None:
    @app.middleware("http")
    async def add_request_id(request: Request, call_next: CallNext) -> Response:
        supplied = request.headers.get("X-Request-Id", "")
        # 只接受短且可打印的客户端 ID，拒绝换行和头部注入字符。
        value = supplied if REQUEST_ID.fullmatch(supplied) else f"req_{uuid4().hex}"
        request.state.request_id = value
        response = await call_next(request)
        response.headers["X-Request-Id"] = value
        return response

    @app.exception_handler(DomainError)
    async def domain_error(request: Request, error: DomainError) -> JSONResponse:
        return problem(request, error.status, error.code, error.detail)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, error: RequestValidationError) -> JSONResponse:
        # 只给出字段路径和校验消息，不回显客户端提交的原始值。
        parts = [
            f"{'.'.join(str(item) for item in entry.get('loc', ()))}: {entry.get('msg', 'invalid')}"
            for entry in error.errors()
        ]
        return problem(request, 422, "VALIDATION_ERROR", "; ".join(parts) or "请求参数不合法。")

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, error: StarletteHTTPException) -> JSONResponse:
        code = HTTP_CODES.get(error.status_code, "HTTP_ERROR")
        detail = "没有找到请求的资源。" if error.status_code == 404 else "请求无法处理。"
        return problem(request, error.status_code, code, detail)

    @app.exception_handler(Exception)
    async def internal_error(request: Request, error: Exception) -> JSONResponse:
        logger.error(
            "unhandled error",
            extra={"event": "http.unhandled", "requestId": request_id(request)},
        )
        return problem(request, 500, "INTERNAL_ERROR", "服务内部错误。")
