import hashlib
import json
import shutil
import socket
import subprocess
import sys
import threading
import time
import wave
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, ClassVar

import pytest

from looplish_api.domain.errors import ProcessingFailure, SourceNotSupported
from looplish_api.infrastructure.media import command_runner, ytdlp_downloader
from looplish_api.infrastructure.media.command_runner import CommandRunner
from looplish_api.infrastructure.media.ffmpeg_processor import FfmpegProcessor
from looplish_api.infrastructure.media.ytdlp_downloader import (
    SafeYoutubeDL,
    YtDlpDownloader,
    validate_public_http_url,
)

PUBLIC_IP = "93.184.216.34"


class RecordingRunner(CommandRunner):
    def __init__(self, stdout: str = "") -> None:
        self.calls: list[list[str]] = []
        self.stdout = stdout

    def run(
        self, args: list[str], timeout: float, cwd: Path | None = None
    ) -> subprocess.CompletedProcess[str]:
        self.calls.append(args)
        return super().completed(args, stdout=self.stdout)


def probe_output(duration: str) -> str:
    return json.dumps({"format": {"duration": duration}})


class ScriptedRunner(RecordingRunner):
    # ffprobe 返回指定音轨；可让「直接拷贝」那次 ffmpeg 调用失败，覆盖回退路径。
    def __init__(self, codec: str = "aac", channels: int = 2, fail_copy: bool = False) -> None:
        super().__init__()
        self.probe = json.dumps({"streams": [{"codec_name": codec, "channels": channels}]})
        self.fail_copy = fail_copy

    def run(
        self, args: list[str], timeout: float, cwd: Path | None = None
    ) -> subprocess.CompletedProcess[str]:
        self.calls.append(args)
        if args[0] == "ffprobe":
            return CommandRunner.completed(args, stdout=self.probe)
        if self.fail_copy and "copy" in args:
            raise ProcessingFailure("MEDIA_PROCESSING_FAILED", "媒体处理失败。")
        return CommandRunner.completed(args)


AUDIO_PROBE = ["-v", "error", "-select_streams", "a:0",
               "-show_entries", "stream=codec_name,channels", "-of", "json"]  # fmt: skip
ENCODE_TAIL = ["-ar", "44100", "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart"]


# ---------------------------------------------------------------- FFmpeg 参数合同


def test_web_audio_copies_aac_stream(tmp_path: Path) -> None:
    runner = ScriptedRunner(codec="aac", channels=2)

    FfmpegProcessor("ffmpeg", "ffprobe", runner).to_web_audio(
        tmp_path / "in.mp4", tmp_path / "out.m4a"
    )

    assert runner.calls == [
        ["ffprobe", *AUDIO_PROBE, str(tmp_path / "in.mp4")],
        [
            "ffmpeg", "-hide_banner", "-nostdin", "-y", "-i", str(tmp_path / "in.mp4"),
            "-map", "0:a:0", "-vn", "-c:a", "copy", "-movflags", "+faststart",
            str(tmp_path / "out.m4a"),
        ],
    ]  # fmt: skip


def test_web_audio_reencodes_when_copy_fails(tmp_path: Path) -> None:
    runner = ScriptedRunner(codec="aac", channels=2, fail_copy=True)
    target = tmp_path / "out.m4a"
    target.write_bytes(b"partial")

    FfmpegProcessor("ffmpeg", "ffprobe", runner).to_web_audio(tmp_path / "in.mkv", target)

    assert len(runner.calls) == 3
    assert runner.calls[2] == [
        "ffmpeg", "-hide_banner", "-nostdin", "-y", "-i", str(tmp_path / "in.mkv"),
        "-map", "0:a:0", "-vn", *ENCODE_TAIL, str(target),
    ]  # fmt: skip
    assert not target.exists()


@pytest.mark.parametrize(("channels", "downmix"), [(1, []), (2, []), (6, ["-ac", "2"])])
def test_web_audio_encodes_other_codecs_keeping_stereo(
    tmp_path: Path, channels: int, downmix: list[str]
) -> None:
    runner = ScriptedRunner(codec="opus", channels=channels)

    FfmpegProcessor("ffmpeg", "ffprobe", runner).to_web_audio(
        tmp_path / "in.webm", tmp_path / "out.m4a"
    )

    assert runner.calls[1] == [
        "ffmpeg", "-hide_banner", "-nostdin", "-y", "-i", str(tmp_path / "in.webm"),
        "-map", "0:a:0", "-vn", *downmix, *ENCODE_TAIL, str(tmp_path / "out.m4a"),
    ]  # fmt: skip


@pytest.mark.parametrize("stdout", ['{"streams": []}', "{}", "not json"])
def test_probe_audio_rejects_media_without_audio(tmp_path: Path, stdout: str) -> None:
    processor = FfmpegProcessor("ffmpeg", "ffprobe", RecordingRunner(stdout=stdout))

    with pytest.raises(ProcessingFailure, match="没有可用的音轨"):
        processor.probe_audio(tmp_path / "in.mp4")


@pytest.mark.parametrize(
    ("method", "codec"),
    [
        ("to_asr_wav", ["-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le"]),
        ("to_asr_mp3", ["-vn", "-ac", "1", "-ar", "16000", "-c:a", "libmp3lame", "-b:a", "32k"]),
    ],
)
def test_asr_outputs_use_exact_contract(tmp_path: Path, method: str, codec: list[str]) -> None:
    runner = RecordingRunner()
    getattr(FfmpegProcessor("ffmpeg", "ffprobe", runner), method)(
        tmp_path / "in.mp4", tmp_path / "out"
    )

    assert runner.calls[0] == [
        "ffmpeg", "-hide_banner", "-nostdin", "-y", "-i", str(tmp_path / "in.mp4"),
        *codec, str(tmp_path / "out"),
    ]  # fmt: skip


@pytest.mark.parametrize(
    ("method", "codec"),
    [
        ("slice_audio", ["-vn", "-ar", "44100", "-c:a", "libmp3lame", "-b:a", "128k"]),
        ("slice_asr_mp3", ["-vn", "-ac", "1", "-ar", "16000", "-c:a", "libmp3lame", "-b:a", "32k"]),
    ],
)
def test_slices_seek_before_input_with_millisecond_window(
    tmp_path: Path, method: str, codec: list[str]
) -> None:
    runner = RecordingRunner()
    getattr(FfmpegProcessor("ffmpeg", "ffprobe", runner), method)(
        tmp_path / "in.m4a", tmp_path / "out.mp3", 1.23456, 2.5
    )

    assert runner.calls[0] == [
        "ffmpeg", "-hide_banner", "-nostdin", "-y", "-ss", "1.235", "-t", "2.500",
        "-i", str(tmp_path / "in.m4a"), *codec, str(tmp_path / "out.mp3"),
    ]  # fmt: skip


def test_convert_creates_target_directory(tmp_path: Path) -> None:
    target = tmp_path / "nested" / "dir" / "out.wav"

    FfmpegProcessor("ffmpeg", "ffprobe", RecordingRunner()).to_asr_wav(tmp_path / "in", target)

    assert target.parent.is_dir()


def test_probe_duration_reads_ffprobe_json(tmp_path: Path) -> None:
    runner = RecordingRunner(stdout=probe_output("10.250000"))

    duration = FfmpegProcessor("ffmpeg", "ffprobe", runner).probe_duration(tmp_path / "in.mp4")

    assert duration == 10.25
    assert runner.calls[0] == [
        "ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json",
        str(tmp_path / "in.mp4"),
    ]  # fmt: skip


@pytest.mark.parametrize(
    "stdout",
    [
        probe_output("N/A"),
        probe_output("0"),
        probe_output("-1"),
        "{}",
        "not json",
        probe_output("nan"),
    ],
)
def test_probe_duration_rejects_unreadable_output(tmp_path: Path, stdout: str) -> None:
    processor = FfmpegProcessor("ffmpeg", "ffprobe", RecordingRunner(stdout=stdout))

    with pytest.raises(ProcessingFailure, match="无法读取媒体时长"):
        processor.probe_duration(tmp_path / "in.mp4")


def test_probe_duration_enforces_max_media_seconds(tmp_path: Path) -> None:
    processor = FfmpegProcessor(
        "ffmpeg", "ffprobe", RecordingRunner(stdout=probe_output("100.5")), max_media_seconds=100
    )

    with pytest.raises(ProcessingFailure, match="超过配置上限"):
        processor.probe_duration(tmp_path / "in.mp4")


# ---------------------------------------------------------------- CommandRunner


def test_command_failure_maps_to_stable_error() -> None:
    runner = CommandRunner()
    with pytest.raises(ProcessingFailure, match="MEDIA_PROCESSING_FAILED") as exc:
        runner.check_result(["ffmpeg"], 1, "secret stderr", returncode=1)
    assert "secret stderr" not in str(exc.value)


def test_run_returns_stdout_and_truncated_stderr() -> None:
    script = "import sys; print('out'); sys.stderr.write('e' * 10000)"

    result = CommandRunner().run([sys.executable, "-c", script], timeout=30)

    assert result.stdout.strip() == "out"
    assert len(result.stderr) == CommandRunner.stderr_limit


def test_run_maps_nonzero_exit_without_leaking_stderr() -> None:
    script = "import sys; sys.stderr.write('token=abc123'); sys.exit(3)"

    with pytest.raises(ProcessingFailure) as exc:
        CommandRunner().run([sys.executable, "-c", script], timeout=30)

    assert exc.value.code == "MEDIA_PROCESSING_FAILED"
    assert "3" in exc.value.detail
    assert "abc123" not in str(exc.value)


def test_missing_executable_names_the_tool_without_leaking_path(tmp_path: Path) -> None:
    with pytest.raises(ProcessingFailure, match="找不到媒体工具 ffprobe") as exc:
        CommandRunner().run([str(tmp_path / "ffprobe")], timeout=5)

    assert exc.value.code == "MEDIA_PROCESSING_FAILED"
    assert "FFmpeg" in exc.value.detail
    assert str(tmp_path) not in str(exc.value)


def test_unexecutable_tool_maps_to_stable_error(tmp_path: Path) -> None:
    tool = tmp_path / "ffmpeg"
    tool.write_text("")
    tool.chmod(0o644)

    with pytest.raises(ProcessingFailure, match="无法启动") as exc:
        CommandRunner().run([str(tool)], timeout=5)

    assert str(tmp_path) not in str(exc.value)


def test_real_timeout_kills_process_tree_quickly() -> None:
    # 父进程再派生一个长时间运行的子进程，两者都必须被终止。
    script = (
        "import subprocess, sys, time;"
        "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)']);"
        "time.sleep(60)"
    )
    began = time.monotonic()

    with pytest.raises(ProcessingFailure, match="超时"):
        CommandRunner().run([sys.executable, "-c", script], timeout=1)

    assert time.monotonic() - began < 20


class FakeProcess:
    pid = 4242
    returncode: int | None = -9

    def __init__(self) -> None:
        self.calls = 0

    def communicate(self, timeout: float | None = None) -> tuple[str, str]:
        self.calls += 1
        if self.calls == 1:
            raise subprocess.TimeoutExpired(["tool"], timeout or 0)
        return "", ""


def test_windows_timeout_uses_taskkill_tree(monkeypatch: pytest.MonkeyPatch) -> None:
    killed: list[list[str]] = []
    monkeypatch.setattr(command_runner.sys, "platform", "win32")
    monkeypatch.setattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x200, raising=False)
    monkeypatch.setattr(subprocess, "Popen", lambda *args, **kwargs: FakeProcess())
    monkeypatch.setattr(subprocess, "run", lambda args, **kwargs: killed.append(args))

    with pytest.raises(ProcessingFailure, match="超时"):
        CommandRunner().run(["tool"], timeout=1)

    assert killed == [["taskkill", "/PID", "4242", "/T", "/F"]]


def test_posix_timeout_kills_process_group(monkeypatch: pytest.MonkeyPatch) -> None:
    killed: list[tuple[int, int]] = []
    monkeypatch.setattr(command_runner.sys, "platform", "linux")
    monkeypatch.setattr(subprocess, "Popen", lambda *args, **kwargs: FakeProcess())
    monkeypatch.setattr(command_runner.os, "getpgid", lambda pid: pid + 1, raising=False)
    monkeypatch.setattr(
        command_runner.os, "killpg", lambda group, sig: killed.append((group, sig)), raising=False
    )
    monkeypatch.setattr(command_runner.signal, "SIGKILL", 9, raising=False)

    with pytest.raises(ProcessingFailure, match="超时"):
        CommandRunner().run(["tool"], timeout=1)

    assert killed == [(4243, 9)]


def test_spawn_never_uses_shell_and_isolates_process_group(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, Any] = {}

    class Done:
        returncode = 0

        def communicate(self, timeout: float | None = None) -> tuple[str, str]:
            return "", ""

    def fake_popen(args: list[str], **kwargs: Any) -> Done:
        seen.update(kwargs)
        return Done()

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    CommandRunner().run(["tool", "a b"], timeout=1)

    assert seen["shell"] is False
    assert seen["stdin"] is subprocess.DEVNULL
    if sys.platform == "win32":
        assert seen["creationflags"] & subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        assert seen["start_new_session"] is True


# ---------------------------------------------------------------- URL 校验


def fake_resolver(mapping: dict[str, list[str]]) -> Any:
    real = ytdlp_downloader._resolve

    def resolve(host: str, port: int) -> list[str]:
        return mapping[host] if host in mapping else real(host, port)

    return resolve


@pytest.mark.parametrize(
    "url",
    ["http://example.test/watch", "https://example.test:8443/a?b=c", "HTTPS://EXAMPLE.TEST/x"],
)
def test_accepts_public_http_urls(monkeypatch: pytest.MonkeyPatch, url: str) -> None:
    monkeypatch.setattr(ytdlp_downloader, "_resolve", fake_resolver({"example.test": [PUBLIC_IP]}))

    validate_public_http_url(url)


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost/",
        "http://127.0.0.1/",
        "http://127.8.9.10:8080/",
        "http://[::1]/",
        "http://10.1.2.3/",
        "http://172.16.0.1/",
        "http://192.168.1.1/",
        "http://169.254.169.254/latest/meta-data",
        "http://[fe80::1]/",
        "http://0.0.0.0/",
        "http://100.64.0.1/",
        "http://224.0.0.1/",
        "http://240.0.0.1/",
        "http://[::ffff:127.0.0.1]/",
    ],
)
def test_rejects_non_public_addresses(url: str) -> None:
    with pytest.raises(SourceNotSupported, match="不允许的网络地址"):
        validate_public_http_url(url)


@pytest.mark.parametrize(
    "url", ["ftp://example.test/a", "file:///etc/passwd", "http:///nohost", "javascript:alert(1)"]
)
def test_rejects_non_http_urls(url: str) -> None:
    with pytest.raises(SourceNotSupported, match="只支持 HTTP"):
        validate_public_http_url(url)


def test_rejects_when_any_resolved_address_is_private(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        ytdlp_downloader,
        "_resolve",
        fake_resolver({"mixed.test": [PUBLIC_IP, "10.0.0.5"]}),
    )

    with pytest.raises(SourceNotSupported, match="不允许的网络地址"):
        validate_public_http_url("https://mixed.test/")


def test_dns_failure_maps_to_stable_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(host: str, port: int) -> list[str]:
        raise socket.gaierror("no such host")

    monkeypatch.setattr(ytdlp_downloader, "_resolve", fail)

    with pytest.raises(SourceNotSupported, match="无法解析"):
        validate_public_http_url("https://missing.test/")


# ---------------------------------------------------------------- 重定向端到端


class RedirectServer:
    def __init__(self) -> None:
        self.paths: list[str] = []
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                owner.paths.append(self.path)
                port = self.server.server_address[1]
                targets = {
                    "/to-private": f"http://127.0.0.1:{port}/secret",
                    "/to-public": f"http://public.test:{port}/ok",
                }
                if self.path in targets:
                    self.send_response(302)
                    self.send_header("Location", targets[self.path])
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                body = b"ok"
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args: object) -> None:
                return

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def public_test_host(monkeypatch: pytest.MonkeyPatch) -> Iterator[RedirectServer]:
    server = RedirectServer()
    real_getaddrinfo = socket.getaddrinfo

    def connect_to_local(host: Any, *args: Any, **kwargs: Any) -> Any:
        # 校验阶段把 public.test 视为公网地址，真正建连时指向本机测试服务。
        return real_getaddrinfo("127.0.0.1" if host == "public.test" else host, *args, **kwargs)

    monkeypatch.setattr(socket, "getaddrinfo", connect_to_local)
    monkeypatch.setattr(ytdlp_downloader, "_resolve", fake_resolver({"public.test": [PUBLIC_IP]}))
    for name in (
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "http_proxy",
        "https_proxy",
        "all_proxy",
    ):
        monkeypatch.delenv(name, raising=False)
    yield server
    server.close()


def exception_chain(error: BaseException | None) -> list[BaseException]:
    chain: list[BaseException] = []
    while error is not None and error not in chain:
        chain.append(error)
        error = error.__cause__ or error.__context__
    return chain


def test_redirect_to_private_address_is_blocked_before_connecting(
    public_test_host: RedirectServer,
) -> None:
    with SafeYoutubeDL({"quiet": True, "proxy": ""}) as client, pytest.raises(Exception) as exc:
        client.urlopen(f"http://public.test:{public_test_host.port}/to-private")

    assert any(isinstance(item, SourceNotSupported) for item in exception_chain(exc.value))
    assert public_test_host.paths == ["/to-private"]


def test_redirect_to_public_address_is_followed(public_test_host: RedirectServer) -> None:
    with SafeYoutubeDL({"quiet": True, "proxy": ""}) as client:
        response = client.urlopen(f"http://public.test:{public_test_host.port}/to-public")
        body = response.read()

    assert body == b"ok"
    assert public_test_host.paths == ["/to-public", "/ok"]


def test_direct_private_request_is_blocked(public_test_host: RedirectServer) -> None:
    with SafeYoutubeDL({"quiet": True, "proxy": ""}) as client, pytest.raises(SourceNotSupported):
        client.urlopen(f"http://127.0.0.1:{public_test_host.port}/secret")

    assert public_test_host.paths == []


def test_only_guarded_request_handler_is_used() -> None:
    with SafeYoutubeDL({"quiet": True}) as client:
        assert set(client._request_director.handlers) == {"Urllib"}


# ---------------------------------------------------------------- 下载器


class FakeYoutubeDL:
    instances: ClassVar[list["FakeYoutubeDL"]] = []
    payload_size = 10
    filepath: str | None = None
    subtitles: ClassVar[dict[str, Any]] = {}
    error: Exception | None = None

    def __init__(self, options: dict[str, Any]) -> None:
        self.options = options
        FakeYoutubeDL.instances.append(self)

    def __enter__(self) -> "FakeYoutubeDL":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def extract_info(self, url: str, download: bool) -> dict[str, Any]:
        if self.error is not None:
            raise self.error
        path = Path(self.options["outtmpl"].replace("%(ext)s", "m4a"))
        path.write_bytes(b"a" * self.payload_size)
        return {
            "title": "Talk",
            "uploader": "Speaker",
            "webpage_url": "https://example.test/watch?v=1",
            "thumbnail": "https://example.test/t.jpg",
            "requested_downloads": [{"filepath": self.filepath or str(path)}],
            "requested_subtitles": self.subtitles,
        }

    def prepare_filename(self, info: dict[str, Any]) -> str:
        raise AssertionError("requested_downloads should be preferred")


@pytest.fixture
def fake_ydl(monkeypatch: pytest.MonkeyPatch) -> type[FakeYoutubeDL]:
    FakeYoutubeDL.instances = []
    FakeYoutubeDL.payload_size = 10
    FakeYoutubeDL.filepath = None
    FakeYoutubeDL.subtitles = {}
    FakeYoutubeDL.error = None
    monkeypatch.setattr(ytdlp_downloader, "SafeYoutubeDL", FakeYoutubeDL)
    monkeypatch.setattr(ytdlp_downloader, "_resolve", fake_resolver({"example.test": [PUBLIC_IP]}))
    return FakeYoutubeDL


def test_downloader_options_disable_playlists_and_auto_subtitles(
    tmp_path: Path, fake_ydl: type[FakeYoutubeDL]
) -> None:
    YtDlpDownloader(max_download_bytes=1000).download(
        "https://example.test/watch?v=1", tmp_path, ("en", "en-US")
    )

    options = fake_ydl.instances[0].options
    assert options["noplaylist"] is True
    assert options["writesubtitles"] is True
    assert options["writeautomaticsub"] is False
    assert options["subtitleslangs"] == ["en", "en-US"]
    assert options["subtitlesformat"] == "vtt/srt"
    assert options["retries"] == 3
    assert options["max_filesize"] == 1000
    assert options["external_downloader"] == {"default": "native"}
    assert options["outtmpl"] == str(tmp_path / "source.%(ext)s")


def test_download_returns_media_info_with_subtitles_inside_workdir(
    tmp_path: Path, fake_ydl: type[FakeYoutubeDL]
) -> None:
    inside = tmp_path / "source.en.vtt"
    inside.write_text("WEBVTT\n", encoding="utf-8")
    outside = tmp_path.parent / f"{tmp_path.name}-outside.vtt"
    outside.write_text("WEBVTT\n", encoding="utf-8")
    fake_ydl.subtitles = {
        "en": {"filepath": str(inside)},
        "fr": {"filepath": str(outside)},
        "de": {"filepath": str(tmp_path / "missing.de.vtt")},
        "es": {},
    }

    info = YtDlpDownloader(1000).download("https://example.test/watch?v=1", tmp_path, ("en",))

    assert info.path == (tmp_path / "source.m4a").resolve()
    assert info.title == "Talk"
    assert info.uploader == "Speaker"
    assert info.source_url == "https://example.test/watch?v=1"
    assert info.thumbnail_url == "https://example.test/t.jpg"
    assert info.subtitle_paths == (inside.resolve(),)


def test_oversized_download_is_deleted(tmp_path: Path, fake_ydl: type[FakeYoutubeDL]) -> None:
    fake_ydl.payload_size = 2000

    with pytest.raises(ProcessingFailure, match="超过配置上限") as exc:
        YtDlpDownloader(1000).download("https://example.test/watch?v=1", tmp_path, ())

    assert exc.value.code == "DOWNLOAD_FAILED"
    assert not (tmp_path / "source.m4a").exists()


def test_download_outside_workdir_is_rejected(
    tmp_path: Path, fake_ydl: type[FakeYoutubeDL]
) -> None:
    workdir = tmp_path / "job"
    elsewhere = tmp_path / "elsewhere.m4a"
    elsewhere.write_bytes(b"x")
    fake_ydl.filepath = str(elsewhere)

    with pytest.raises(ProcessingFailure, match="不在任务目录") as exc:
        YtDlpDownloader(1000).download("https://example.test/watch?v=1", workdir, ())

    assert exc.value.code == "DOWNLOAD_FAILED"


def test_extractor_errors_map_to_download_failed(
    tmp_path: Path, fake_ydl: type[FakeYoutubeDL]
) -> None:
    fake_ydl.error = RuntimeError("HTTP Error 403: token=secret")

    with pytest.raises(ProcessingFailure) as exc:
        YtDlpDownloader(1000).download("https://example.test/watch?v=1", tmp_path, ())

    assert exc.value.code == "DOWNLOAD_FAILED"
    assert "secret" not in str(exc.value)


def test_private_url_is_rejected_before_downloader_starts(
    tmp_path: Path, fake_ydl: type[FakeYoutubeDL]
) -> None:
    with pytest.raises(SourceNotSupported):
        YtDlpDownloader(1000).download("http://127.0.0.1/video", tmp_path / "job", ())

    assert fake_ydl.instances == []
    assert not (tmp_path / "job").exists()


# ---------------------------------------------------------------- 真实 FFmpeg

FFMPEG = shutil.which("ffmpeg")
FFPROBE = shutil.which("ffprobe")
needs_ffmpeg = pytest.mark.skipif(
    FFMPEG is None or FFPROBE is None, reason="ffmpeg/ffprobe not installed"
)


def square_wave(path: Path, seconds: float = 1.0, rate: int = 16000) -> None:
    # 固定整数方波，不依赖浮点三角函数，跨平台字节一致。
    frames = bytearray()
    for index in range(int(seconds * rate)):
        value = 8000 if (index // 40) % 2 == 0 else -8000
        frames += value.to_bytes(2, "little", signed=True)
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(rate)
        output.writeframes(bytes(frames))


def stream_info(path: Path) -> dict[str, Any]:
    assert FFPROBE is not None
    completed = subprocess.run(
        [
            FFPROBE, "-v", "error", "-select_streams", "a:0",
            "-show_entries", "stream=codec_name,sample_rate,channels,bit_rate:format=duration",
            "-of", "json", str(path),
        ],
        capture_output=True, text=True, check=True,
    )  # fmt: skip
    data = json.loads(completed.stdout)
    stream = data["streams"][0]
    return {
        "codec": stream["codec_name"],
        "rate": int(stream["sample_rate"]),
        "channels": int(stream["channels"]),
        "bit_rate": int(stream["bit_rate"]) if stream.get("bit_rate", "N/A") != "N/A" else None,
        "duration": float(data["format"]["duration"]),
    }


@needs_ffmpeg
def test_real_ffmpeg_produces_contracted_audio(tmp_path: Path) -> None:
    assert FFMPEG is not None and FFPROBE is not None
    source = tmp_path / "source.wav"
    square_wave(source)
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    processor = FfmpegProcessor(FFMPEG, FFPROBE, CommandRunner())

    assert processor.probe_duration(source) == pytest.approx(1.0, abs=0.01)
    web = stream_info(processor.to_web_audio(source, tmp_path / "audio.m4a"))
    wav = stream_info(processor.to_asr_wav(source, tmp_path / "asr-input.wav"))
    mp3 = stream_info(processor.to_asr_mp3(source, tmp_path / "asr-upload.mp3"))
    asr_slice = stream_info(processor.slice_asr_mp3(source, tmp_path / "asr-part.mp3", 0.25, 0.5))
    clip = stream_info(processor.slice_audio(source, tmp_path / "000001.mp3", 0.2, 0.6))

    assert (web["codec"], web["rate"], web["channels"]) == ("aac", 44100, 1)
    assert web["duration"] == pytest.approx(1.0, abs=0.05)
    assert (wav["codec"], wav["rate"], wav["channels"]) == ("pcm_s16le", 16000, 1)
    assert wav["bit_rate"] == 256000
    assert (mp3["codec"], mp3["rate"], mp3["channels"], mp3["bit_rate"]) == (
        "mp3", 16000, 1, 32000,
    )  # fmt: skip
    assert (asr_slice["codec"], asr_slice["rate"], asr_slice["bit_rate"]) == ("mp3", 16000, 32000)
    assert asr_slice["duration"] == pytest.approx(0.5, abs=0.08)
    assert (clip["codec"], clip["rate"], clip["channels"], clip["bit_rate"]) == (
        "mp3", 44100, 1, 128000,
    )  # fmt: skip
    assert clip["duration"] == pytest.approx(0.6, abs=0.08)
    assert hashlib.sha256(source.read_bytes()).hexdigest() == digest


@needs_ffmpeg
def test_real_ffmpeg_copies_stereo_aac_without_reencoding(tmp_path: Path) -> None:
    assert FFMPEG is not None and FFPROBE is not None
    wav = tmp_path / "source.wav"
    square_wave(wav)
    source = tmp_path / "source.m4a"
    subprocess.run(
        [FFMPEG, "-v", "error", "-y", "-i", str(wav), "-ac", "2", "-c:a", "aac", "-b:a", "128k",
         str(source)],
        check=True,
    )  # fmt: skip
    processor = FfmpegProcessor(FFMPEG, FFPROBE, CommandRunner())

    web = stream_info(processor.to_web_audio(source, tmp_path / "audio.m4a"))
    original = stream_info(source)

    assert (web["codec"], web["channels"]) == ("aac", 2)
    # 直接拷贝不重新编码，码率与原音轨一致（重新编码会变成 160k）。
    assert web["bit_rate"] == pytest.approx(original["bit_rate"], rel=0.01)


@needs_ffmpeg
def test_real_ffmpeg_failure_maps_to_stable_error(tmp_path: Path) -> None:
    assert FFMPEG is not None and FFPROBE is not None
    broken = tmp_path / "broken.mp4"
    broken.write_bytes(b"not media")
    processor = FfmpegProcessor(FFMPEG, FFPROBE, CommandRunner())

    with pytest.raises(ProcessingFailure) as exc:
        processor.to_web_audio(broken, tmp_path / "audio.m4a")

    assert exc.value.code == "MEDIA_PROCESSING_FAILED"
    assert str(tmp_path) not in str(exc.value)


def test_download_progress_reports_media_bytes_but_skips_subtitles() -> None:
    events: list[tuple[float, str]] = []
    hook = ytdlp_downloader.progress_hook(lambda value, text: events.append((value, text)))

    hook({"status": "downloading", "filename": "/w/source.en.vtt", "downloaded_bytes": 9})
    hook(
        {
            "status": "downloading",
            "filename": "/w/source.m4a.part",
            "downloaded_bytes": 6_200_000,
            "total_bytes": 13_800_000,
        }
    )
    hook({"status": "downloading", "filename": "/w/source.m4a", "downloaded_bytes": 1_000_000})
    hook({"status": "finished", "filename": "/w/source.m4a"})

    assert events == [
        (pytest.approx(0.449, abs=1e-3), "下载音频 45% · 6.2 / 13.8 MB"),
        (0.0, "下载音频 · 已下载 1.0 MB"),
    ]


def test_downloader_forwards_progress_hook(tmp_path: Path, fake_ydl: type[FakeYoutubeDL]) -> None:
    events: list[str] = []

    YtDlpDownloader(1000).download(
        "https://example.test/watch?v=1", tmp_path, (), lambda _, text: events.append(text)
    )

    assert events == ["解析视频信息"]
    assert len(fake_ydl.instances[0].options["progress_hooks"]) == 1
