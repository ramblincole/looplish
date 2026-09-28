import json
import logging
from datetime import UTC, datetime
from pathlib import Path

FIELDS = ("event", "requestId", "jobId", "stage", "durationMs", "errorCode")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        # 主体由固定字段构造，不调用 record.getMessage()，避免任意消息泄露内容。
        value: dict[str, object] = {
            "timestamp": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "level": record.levelname,
            "event": getattr(record, "event", record.name),
        }
        for field in FIELDS[1:]:
            item = getattr(record, field, None)
            if item is not None:
                value[field] = item
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def configure_logging(log_dir: Path) -> None:
    log_dir.mkdir(parents=True, exist_ok=True)
    formatter = JsonFormatter()
    stream = logging.StreamHandler()
    stream.setFormatter(formatter)
    file_handler = logging.FileHandler(log_dir / "looplish.jsonl", encoding="utf-8")
    file_handler.setFormatter(formatter)
    root = logging.getLogger()
    # 应用统一接管 root handlers，避免重复输出或沿用包含敏感格式的旧 handler。
    for handler in root.handlers:
        handler.close()
    root.handlers[:] = [stream, file_handler]
    root.setLevel(logging.INFO)
