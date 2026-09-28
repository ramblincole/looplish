import argparse
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from looplish_api.api.dependencies import build_container
from looplish_api.app_factory import create_app
from looplish_api.config import Settings

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "packages" / "contracts" / "openapi.json"


def export(target: Path) -> None:
    with TemporaryDirectory(prefix="looplish-openapi-") as value:
        temporary = Path(value)
        # 隔离所有可写目录并禁用 .env；显式参数优先于进程环境变量，
        # 开发者终端里的 LOOPLISH_* 也不会改变导出结果。
        settings = Settings(
            _env_file=None,
            asr_backend="fake",
            data_dir=temporary / "jobs",
            models_dir=temporary / "models",
            log_dir=temporary / "logs",
            web_dist_dir=None,
        )
        schema = create_app(build_container(settings)).openapi()
    # 临时目录已退出生命周期；只把稳定排序的 Schema 写入仓库生成物。
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(schema, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Export the Looplish OpenAPI contract.")
    parser.add_argument(
        "--output", type=Path, default=TARGET, help="目标文件（默认写入 contracts 包）"
    )
    export(parser.parse_args().output)


if __name__ == "__main__":
    main()
