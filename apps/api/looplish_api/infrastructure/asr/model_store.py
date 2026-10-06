from collections.abc import Callable
from pathlib import Path
from typing import Any

from tqdm.std import tqdm

from looplish_api.domain.errors import ProcessingFailure

# 0~1 的下载比例。
DownloadProgress = Callable[[float], None]


def _download_tracker(expected: int, on_progress: DownloadProgress) -> type[tqdm]:
    """把 huggingface_hub 的进度条换成回调：不往终端输出，只汇报下载比例。"""
    best = 0.0

    class Tracker(tqdm):  # type: ignore[misc]
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            # 按字节计数的有两条：Xet 下载时「Downloading bytes」（网络字节）更新得细，
            # 普通 HTTP 下载时「Reconstructing」（落盘字节）更新得细；文件计数条不用。
            self.counts_bytes = kwargs.get("unit") == "B"
            kwargs["disable"] = True
            super().__init__(*args, **kwargs)

        def update(self, n: float | None = 1) -> bool | None:
            nonlocal best
            # 禁用的 tqdm 不会累加 n，这里自己记账。
            self.n += n or 0
            # 进度条自己的总量随各文件开始下载才陆续累加，小文件先下完时会误报 100%，
            # 所以分母用下载前预估的总字节数；取各条中最大的比例并且只往前报。
            if self.counts_bytes and expected > 0:
                best = max(best, min(1.0, self.n / expected))
                on_progress(best)
            return None

    return Tracker


def ensure_model(
    repo_id: str,
    models_dir: Path,
    on_download: DownloadProgress,
    allow_patterns: list[str] | None = None,
) -> Path:
    """返回模型的本地目录；本地没有时才联网下载，并通过 on_download 报告下载比例。"""
    from huggingface_hub import snapshot_download
    from huggingface_hub.errors import LocalEntryNotFoundError

    try:
        # 已缓存时完全离线加载，省掉每次启动向 Hugging Face 校验版本的网络往返。
        return Path(
            snapshot_download(
                repo_id,
                cache_dir=models_dir,
                allow_patterns=allow_patterns,
                local_files_only=True,
            )
        )
    except LocalEntryNotFoundError:
        pass
    on_download(0.0)
    try:
        # 先只查文件清单拿到总字节数；这一步同样不往服务端终端打印进度条。
        plan = snapshot_download(
            repo_id,
            cache_dir=models_dir,
            allow_patterns=allow_patterns,
            dry_run=True,
            tqdm_class=_download_tracker(0, on_download),
        )
        expected = sum(item.file_size or 0 for item in plan if item.will_download)
        return Path(
            snapshot_download(
                repo_id,
                cache_dir=models_dir,
                allow_patterns=allow_patterns,
                tqdm_class=_download_tracker(expected, on_download),
            )
        )
    except Exception as error:
        raise ProcessingFailure(
            "TRANSCRIPTION_FAILED", "识别模型下载失败，请检查网络后重试。", 502
        ) from error
