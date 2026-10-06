import ipaddress
import socket
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from yt_dlp import YoutubeDL
from yt_dlp.networking import _urllib as ytdlp_urllib
from yt_dlp.networking.exceptions import RequestError

from looplish_api.domain.errors import ProcessingFailure, SourceNotSupported
from looplish_api.domain.models import MediaInfo
from looplish_api.domain.ports import ProgressCallback

# 只保留已加装重定向校验的 urllib 后端；其他网络库会绕开下面的校验。
ALLOWED_REQUEST_HANDLERS = frozenset({"Urllib"})


def _resolve(host: str, port: int) -> list[str]:
    return [str(item[4][0]) for item in socket.getaddrinfo(host, port)]


def validate_public_http_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise SourceNotSupported("只支持 HTTP(S) URL。")
    try:
        addresses = _resolve(
            parsed.hostname,
            parsed.port or (443 if parsed.scheme == "https" else 80),
        )
    except (OSError, ValueError) as error:
        raise SourceNotSupported("无法解析媒体地址。") from error
    for raw in addresses:
        # IPv6 链路本地地址带 `%网卡` 后缀；IPv4 映射地址按其中的 IPv4 判断。
        address = ipaddress.ip_address(raw.split("%", 1)[0])
        if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
            address = address.ipv4_mapped
        # 任一解析结果不是公网地址就拒绝，避免多地址 DNS 绕过检查。
        if not address.is_global or address.is_multicast:
            raise SourceNotSupported("URL 解析到不允许的网络地址。")


class BlockedRedirectError(RequestError):  # type: ignore[misc]
    pass


def _install_redirect_guard() -> None:
    # yt-dlp 在 urllib 内部跟随重定向，不会再经过 YoutubeDL.urlopen，必须在这里逐跳校验。
    handler: Any = ytdlp_urllib.RedirectHandler
    if getattr(handler, "_looplish_guarded", False):
        return
    original = handler.redirect_request

    def redirect_request(
        self: Any, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str
    ) -> Any:
        try:
            validate_public_http_url(newurl)
        except SourceNotSupported as error:
            # 用 yt-dlp 的网络错误类型上抛，它会原样传递而不是当作程序缺陷报告。
            raise BlockedRedirectError(error.detail) from error
        return original(self, req, fp, code, msg, headers, newurl)

    handler.redirect_request = redirect_request
    handler._looplish_guarded = True


class SafeYoutubeDL(YoutubeDL):  # type: ignore[misc]
    def __init__(self, params: dict[str, Any] | None = None, auto_init: bool = True) -> None:
        _install_redirect_guard()
        super().__init__(params, auto_init)

    def build_request_director(self, handlers: Any, preferences: Any = None) -> Any:
        allowed = [handler for handler in handlers if handler.RH_KEY in ALLOWED_REQUEST_HANDLERS]
        return super().build_request_director(allowed, preferences)

    def urlopen(self, request: Any) -> Any:
        target = request if isinstance(request, str) else getattr(request, "url", None)
        if target is None:
            target = request.get_full_url()
        # 页面、清单、分片和字幕请求都会经过这里；重定向由上面的守卫逐跳校验。
        validate_public_http_url(str(target))
        return super().urlopen(request)


SUBTITLE_SUFFIXES = (".vtt", ".srt")


def _megabytes(size: float) -> str:
    return f"{size / 1_000_000:.1f}"


def progress_hook(progress: ProgressCallback) -> Callable[[dict[str, Any]], None]:
    """把 yt-dlp 的下载回调转成「下载音频 45% · 6.2 / 13.8 MB」。"""

    def hook(status: dict[str, Any]) -> None:
        # 字幕文件很小且先于媒体下载，计入会让进度先到 100% 再回落。
        filename = str(status.get("filename") or "").removesuffix(".part")
        if status.get("status") != "downloading" or filename.endswith(SUBTITLE_SUFFIXES):
            return
        done = float(status.get("downloaded_bytes") or 0)
        total = float(status.get("total_bytes") or status.get("total_bytes_estimate") or 0)
        if total <= 0:
            progress(0.0, f"下载音频 · 已下载 {_megabytes(done)} MB")
            return
        ratio = min(1.0, done / total)
        progress(
            ratio,
            f"下载音频 {round(ratio * 100)}% · {_megabytes(done)} / {_megabytes(total)} MB",
        )

    return hook


class YtDlpDownloader:
    def __init__(self, max_download_bytes: int) -> None:
        self.max_download_bytes = max_download_bytes

    def options(
        self,
        workdir: Path,
        subtitle_languages: tuple[str, ...],
        progress: ProgressCallback | None = None,
    ) -> dict[str, Any]:
        return {
            "format": "bestaudio/best",
            "noplaylist": True,
            "retries": 3,
            "max_filesize": self.max_download_bytes,
            "outtmpl": str(workdir / "source.%(ext)s"),
            "writesubtitles": True,
            "writeautomaticsub": False,
            "subtitleslangs": list(subtitle_languages),
            # 解析器只认 SRT/VTT；不指定时 YouTube 会给出 json3 等格式。
            "subtitlesformat": "vtt/srt",
            # 外部下载器（如 FFmpeg 拉 rtmp）会绕开请求校验，只用内置下载器。
            "external_downloader": {"default": "native"},
            "quiet": True,
            "no_warnings": True,
            "progress_hooks": [progress_hook(progress)] if progress is not None else [],
        }

    def download(
        self,
        url: str,
        workdir: Path,
        subtitle_languages: tuple[str, ...],
        progress: ProgressCallback | None = None,
    ) -> MediaInfo:
        validate_public_http_url(url)
        workdir.mkdir(parents=True, exist_ok=True)
        root = workdir.resolve()
        if progress is not None:
            # 解析页面、挑选音轨要几秒，此时还没有字节进度。
            progress(0.0, "解析视频信息")
        try:
            with SafeYoutubeDL(self.options(workdir, subtitle_languages, progress)) as client:
                info = client.extract_info(url, download=True)
                downloads = info.get("requested_downloads") or []
                filepath = downloads[0].get("filepath") if downloads else None
                path = Path(filepath or client.prepare_filename(info)).resolve()
        except Exception as error:
            raise ProcessingFailure("DOWNLOAD_FAILED", "媒体下载失败。") from error
        # 不信任下载器返回的路径和预检大小限制，落盘后再次验证边界。
        if root not in path.parents or not path.is_file():
            raise ProcessingFailure("DOWNLOAD_FAILED", "下载结果不在任务目录。")
        if path.stat().st_size > self.max_download_bytes:
            path.unlink()
            raise ProcessingFailure("DOWNLOAD_FAILED", "下载文件超过配置上限。")
        requested_subtitles = info.get("requested_subtitles") or {}
        subtitle_paths = tuple(
            candidate
            for candidate in (
                Path(value["filepath"]).resolve()
                for value in requested_subtitles.values()
                if value.get("filepath")
            )
            if root in candidate.parents and candidate.is_file()
        )
        return MediaInfo(
            path=path,
            title=str(info.get("title") or path.stem),
            uploader=info.get("uploader"),
            source_url=str(info.get("webpage_url") or url),
            thumbnail_url=info.get("thumbnail"),
            subtitle_paths=subtitle_paths,
        )
