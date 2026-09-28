import os
from pathlib import Path

import pytest
from pydantic import ValidationError

from looplish_api.config import Settings
from looplish_api.domain.models import SegmentationOptions, SubtitleSource

ENV_EXAMPLE = Path(__file__).resolve().parents[4] / ".env.example"


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    # 开发机上的 LOOPLISH_* 变量不能影响默认值断言。
    for name in list(os.environ):
        if name.startswith("LOOPLISH_"):
            monkeypatch.delenv(name)


def test_settings_are_immutable(tmp_path: Path) -> None:
    settings = Settings(_env_file=None, data_dir=tmp_path / "jobs")
    with pytest.raises(ValidationError, match="frozen"):
        settings.host = "0.0.0.0"  # type: ignore[misc]


def test_default_host_is_loopback(tmp_path: Path) -> None:
    assert Settings(_env_file=None, data_dir=tmp_path / "jobs").host == "127.0.0.1"


def test_unknown_backend_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="unknown ASR backend"):
        Settings(_env_file=None, data_dir=tmp_path / "jobs", asr_backend="missing")


def test_cloud_backend_requires_key(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="API key"):
        Settings(_env_file=None, data_dir=tmp_path / "jobs", asr_backend="openai")


def test_cloud_backend_rejects_blank_key(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="API key"):
        Settings(_env_file=None, data_dir=tmp_path / "jobs", asr_backend="openai", asr_api_key="  ")


def test_env_example_blank_values_keep_defaults(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # 直接复制 .env.example 作为 .env 时，留空的项必须回落到默认值。
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text(ENV_EXAMPLE.read_text(encoding="utf-8"), encoding="utf-8")
    defaults = Settings(_env_file=None)

    settings = Settings.from_environment()

    assert settings.data_dir == defaults.data_dir
    assert settings.models_dir == defaults.models_dir
    assert settings.log_dir == defaults.log_dir
    assert settings.web_dist_dir is None
    assert settings.ffmpeg_path == defaults.ffmpeg_path
    assert settings.ffprobe_path == defaults.ffprobe_path
    assert settings.asr_api_key is None
    assert settings.asr_base_url is None
    assert settings.asr_api_model is None


def test_blank_api_key_in_env_does_not_satisfy_cloud_backend(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LOOPLISH_ASR_BACKEND", "openai")
    monkeypatch.setenv("LOOPLISH_ASR_API_KEY", "")
    with pytest.raises(ValueError, match="API key"):
        Settings(_env_file=None, data_dir=tmp_path / "jobs")


def test_secret_is_not_in_repr(tmp_path: Path) -> None:
    settings = Settings(
        _env_file=None,
        data_dir=tmp_path / "jobs",
        asr_backend="openai",
        asr_api_key="test-secret-value",
    )
    assert "test-secret-value" not in repr(settings)
    assert "test-secret-value" not in str(settings)


def test_invalid_segmentation_fails_at_startup(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="lower than max_duration"):
        Settings(
            _env_file=None,
            data_dir=tmp_path / "jobs",
            seg_min_seconds=5.0,
            seg_max_seconds=5.0,
        )


def test_from_environment_can_disable_dotenv(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("LOOPLISH_ASR_BACKEND=missing\n", encoding="utf-8")
    monkeypatch.setenv("LOOPLISH_ENV_FILE", "")
    monkeypatch.setenv("LOOPLISH_DATA_DIR", str(tmp_path / "jobs"))
    assert Settings.from_environment().asr_backend == "local"


def test_from_environment_reads_dotenv_by_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("LOOPLISH_ASR_BACKEND=fake\n", encoding="utf-8")
    monkeypatch.setenv("LOOPLISH_DATA_DIR", str(tmp_path / "jobs"))
    assert Settings.from_environment().asr_backend == "fake"


def test_default_job_options_snapshot(tmp_path: Path) -> None:
    settings = Settings(
        _env_file=None,
        data_dir=tmp_path / "jobs",
        subtitle_languages=" en, en-US ,,en-GB ",
        seg_max_seconds=20.0,
    )

    options = settings.default_job_options()

    assert options.asr_backend == "local"
    assert options.asr_model == "small.en"
    assert options.language == "en"
    assert options.subtitle_source is SubtitleSource.AUTO
    assert options.subtitle_languages == ("en", "en-US", "en-GB")
    assert options.make_clips is False
    assert options.segmentation == SegmentationOptions(max_duration=20.0)


def test_empty_language_means_auto_detect(tmp_path: Path) -> None:
    settings = Settings(_env_file=None, data_dir=tmp_path / "jobs", language="")

    assert settings.default_job_options().language is None


def test_auto_language_means_auto_detect(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOOPLISH_LANGUAGE", "auto")
    settings = Settings(_env_file=None, data_dir=tmp_path / "jobs")

    assert settings.default_job_options().language is None


def test_job_options_do_not_carry_secret(tmp_path: Path) -> None:
    settings = Settings(
        _env_file=None,
        data_dir=tmp_path / "jobs",
        asr_backend="groq",
        asr_api_key="test-secret-value",
    )

    assert "test-secret-value" not in repr(settings.default_job_options())


@pytest.mark.parametrize(
    ("host", "expected"),
    [
        ("127.0.0.1", True),
        ("127.8.8.8", True),
        ("localhost", True),
        ("::1", True),
        ("[::1]", True),
        ("0.0.0.0", False),
        ("::", False),
        ("192.168.1.20", False),
        ("looplish.example", False),
    ],
)
def test_local_paths_follow_loopback_by_default(tmp_path: Path, host: str, expected: bool) -> None:
    settings = Settings(_env_file=None, data_dir=tmp_path / "jobs", host=host)

    assert settings.listens_on_loopback is expected
    assert settings.local_paths_enabled is expected


@pytest.mark.parametrize("value", ["true", "false"])
def test_local_paths_switch_overrides_host(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    monkeypatch.setenv("LOOPLISH_ALLOW_LOCAL_PATHS", value)
    monkeypatch.setenv("LOOPLISH_HOST", "0.0.0.0" if value == "true" else "127.0.0.1")

    settings = Settings(_env_file=None, data_dir=tmp_path / "jobs")

    assert settings.local_paths_enabled is (value == "true")
