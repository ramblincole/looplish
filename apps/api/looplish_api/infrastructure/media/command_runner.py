from __future__ import annotations

import contextlib
import os
import signal
import subprocess
import sys
from pathlib import Path

from looplish_api.domain.errors import ProcessingFailure


class CommandRunner:
    stderr_limit = 8192

    @staticmethod
    def completed(args: list[str], stdout: str = "") -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(args, 0, stdout, "")

    def run(
        self,
        args: list[str],
        timeout: float,
        cwd: Path | None = None,
    ) -> subprocess.CompletedProcess[str]:
        try:
            process = self._spawn(args, cwd)
        except OSError as error:
            # 工具不存在或无权执行时同样给出稳定错误码，不暴露本机路径。
            raise ProcessingFailure("MEDIA_PROCESSING_FAILED", "媒体工具无法启动。") from error
        try:
            stdout, stderr = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired as error:
            # Windows 与 POSIX 的进程树终止机制不同，但都不能只杀父进程。
            self._kill_tree(process)
            process.communicate()
            raise ProcessingFailure("MEDIA_PROCESSING_FAILED", "媒体处理超时。") from error
        returncode = process.returncode
        if returncode is None:
            raise RuntimeError("child process did not exit after communicate")
        return self.check_result(
            args,
            timeout,
            # 只把有限的 stderr 留在进程边界，领域错误中不暴露原始输出。
            stderr[-self.stderr_limit :],
            returncode,
            stdout,
        )

    @staticmethod
    def _spawn(args: list[str], cwd: Path | None) -> subprocess.Popen[str]:
        # 为每次调用建立独立进程组，超时时才能连同工具派生的子进程一起终止。
        if sys.platform == "win32":
            return subprocess.Popen(
                args,
                cwd=cwd,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                shell=False,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
            )
        return subprocess.Popen(
            args,
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            shell=False,
            start_new_session=True,
        )

    @staticmethod
    def _kill_tree(process: subprocess.Popen[str]) -> None:
        if sys.platform == "win32":
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                capture_output=True,
                check=False,
                shell=False,
            )
        else:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(os.getpgid(process.pid), signal.SIGKILL)

    def check_result(
        self,
        args: list[str],
        timeout: float,
        stderr: str,
        returncode: int,
        stdout: str = "",
    ) -> subprocess.CompletedProcess[str]:
        if returncode != 0:
            raise ProcessingFailure(
                "MEDIA_PROCESSING_FAILED",
                f"媒体工具执行失败，退出码 {returncode}。",
            )
        return subprocess.CompletedProcess(args, returncode, stdout, stderr)
