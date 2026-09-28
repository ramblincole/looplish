from dataclasses import dataclass


@dataclass(eq=False)
class DomainError(Exception):
    code: str
    detail: str
    status: int

    def __str__(self) -> str:
        return f"{self.code}: {self.detail}"


class JobNotFound(DomainError):
    def __init__(self) -> None:
        super().__init__("JOB_NOT_FOUND", "没有找到指定任务。", 404)


class JobNotReady(DomainError):
    def __init__(self) -> None:
        super().__init__("JOB_NOT_READY", "任务尚未处理完成。", 409)


class JobRunning(DomainError):
    def __init__(self) -> None:
        super().__init__("JOB_RUNNING", "运行中的任务不能删除。", 409)


class WordsNotAvailable(DomainError):
    def __init__(self) -> None:
        super().__init__("WORDS_NOT_AVAILABLE", "结果中没有词级时间戳。", 400)


class InvalidJobOptions(DomainError):
    def __init__(self, detail: str = "任务参数不可用。") -> None:
        super().__init__("INVALID_JOB_OPTIONS", detail, 422)


class SourceNotSupported(DomainError):
    def __init__(self, detail: str = "不支持该媒体来源。") -> None:
        super().__init__("SOURCE_NOT_SUPPORTED", detail, 400)


class ProcessingFailure(DomainError):
    def __init__(self, code: str, detail: str, status: int = 422) -> None:
        super().__init__(code, detail, status)
