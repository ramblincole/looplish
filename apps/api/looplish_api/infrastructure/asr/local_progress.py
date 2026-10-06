from looplish_api.domain.ports import ProgressCallback

# 本次需要下载模型时，下载占转写阶段进度的前 30%；模型已在本地时识别独占整段。
MODEL_DOWNLOAD_SHARE = 0.3


def clock(seconds: float) -> str:
    total = max(0, int(seconds))
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02}:{secs:02}" if hours else f"{minutes}:{secs:02}"


class LocalProgress:
    """本地识别各步骤的进度文案；模型下载与识别共用转写阶段，进度不会倒退。"""

    def __init__(self, sink: ProgressCallback | None) -> None:
        self.sink = sink
        self.offset = 0.0

    def _emit(self, value: float, message: str) -> None:
        if self.sink is not None:
            self.sink(value, message)

    def model_download(self, ratio: float) -> None:
        self.offset = MODEL_DOWNLOAD_SHARE
        percent = round(min(1.0, max(0.0, ratio)) * 100)
        self._emit(MODEL_DOWNLOAD_SHARE * ratio, f"首次使用，下载识别模型 {percent}%")

    def model_loading(self) -> None:
        self._emit(self.offset, "加载识别模型")

    def detecting_speech(self) -> None:
        self._emit(self.offset, "检测人声片段")

    def recognized(self, position: float, duration: float) -> None:
        if duration <= 0:
            return
        ratio = min(1.0, max(0.0, position / duration))
        self._emit(
            self.offset + (1 - self.offset) * ratio,
            f"识别语音 {clock(min(position, duration))} / {clock(duration)}",
        )
