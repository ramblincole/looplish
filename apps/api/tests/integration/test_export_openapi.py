import json
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
SCRIPT = REPO / "scripts" / "export_openapi.py"
COMMITTED = REPO / "packages" / "contracts" / "openapi.json"
SECRET = "sk-test-secret-value-123"


def run_export(tmp_path: Path, output: Path) -> subprocess.CompletedProcess[str]:
    # 工作目录里放一份含测试 Key 的 .env，环境变量里也放会改变装配的 LOOPLISH_*：
    # 导出结果必须与二者都无关。
    (tmp_path / ".env").write_text(
        f"LOOPLISH_ASR_BACKEND=openai\nLOOPLISH_ASR_API_KEY={SECRET}\n", encoding="utf-8"
    )
    env = {key: value for key, value in os.environ.items() if not key.startswith("LOOPLISH_")}
    env.update(
        {
            "LOOPLISH_DATA_DIR": str(tmp_path / "should-not-exist" / "jobs"),
            "LOOPLISH_LOG_DIR": str(tmp_path / "should-not-exist" / "logs"),
            "LOOPLISH_WEB_DIST_DIR": str(tmp_path / "missing-web"),
            "LOOPLISH_ASR_API_KEY": SECRET,
        }
    )
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--output", str(output)],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )


def test_export_is_isolated_from_dotenv_and_environment(tmp_path: Path) -> None:
    output = tmp_path / "out" / "openapi.json"

    completed = run_export(tmp_path, output)

    assert completed.returncode == 0, completed.stderr
    text = output.read_text(encoding="utf-8")
    assert SECRET not in text
    assert not (tmp_path / "should-not-exist").exists()
    assert json.loads(text)["paths"]["/api/v1/jobs"]


def test_committed_contract_matches_current_api(tmp_path: Path) -> None:
    # 改了接口却没重新导出契约时，这里会失败，提示运行 scripts/export_openapi.py。
    output = tmp_path / "openapi.json"

    completed = run_export(tmp_path, output)

    assert completed.returncode == 0, completed.stderr
    assert output.read_bytes() == COMMITTED.read_bytes(), (
        "packages/contracts/openapi.json 已过期：运行 "
        "uv run --project apps/api python scripts/export_openapi.py 并重新生成类型"
    )


def test_contract_declares_problem_details_for_errors() -> None:
    schema = json.loads(COMMITTED.read_text(encoding="utf-8"))

    assert "ProblemDetails" in schema["components"]["schemas"]
    assert "HTTPValidationError" not in schema["components"]["schemas"]
    for path, operations in schema["paths"].items():
        if not path.startswith("/api/"):
            continue
        for operation in operations.values():
            responses = operation["responses"]
            assert "422" not in responses, path
            assert set(responses["4XX"]["content"]) == {"application/problem+json"}, path
