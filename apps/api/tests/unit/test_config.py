import os
from pathlib import Path

import pytest
from pydantic import ValidationError

from looplish_api.config import Settings
from looplish_api.domain.models import SegmentationOptions, SubtitleSource


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


def test_job_options_do_not_carry_secret(tmp_path: Path) -> None:
    settings = Settings(
        _env_file=None,
        data_dir=tmp_path / "jobs",
        asr_backend="groq",
        asr_api_key="test-secret-value",
    )

    assert "test-secret-value" not in repr(settings.default_job_options())
