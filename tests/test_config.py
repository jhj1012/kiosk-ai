"""Tests for config loading, *.local.yaml overrides and the .env file."""

import os
from pathlib import Path

import pytest

from assistant.config import CONFIG_DIR, ConfigError, deep_merge, load_config, load_env_file


def write(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


@pytest.fixture
def config_dir(tmp_path: Path) -> Path:
    write(
        tmp_path / "models.yaml",
        "llm:\n  provider: gemini\n  model: base-model\n  temperature: 0.5\ntts:\n  rate: 180\n",
    )
    write(
        tmp_path / "settings.yaml",
        'target_window:\n  title: "Test Kiosk"\n'
        "agent:\n  max_steps_per_request: 7\n  confirm_before_payment: true\n",
    )
    return tmp_path


def test_deep_merge_merges_nested_dicts() -> None:
    base = {"llm": {"model": "a", "timeout_s": 1}, "x": 1}
    merged = deep_merge(base, {"llm": {"model": "b"}, "y": 2})
    assert merged == {"llm": {"model": "b", "timeout_s": 1}, "x": 1, "y": 2}
    assert base["llm"]["model"] == "a"  # input not modified


def test_load_config_without_local_files(config_dir: Path) -> None:
    config = load_config(config_dir)
    assert config.llm.model == "base-model"
    assert config.llm.thinking_level == "low"  # default
    assert config.llm.api_key_env == "GEMINI_API_KEY"
    assert config.screen.window_title == "Test Kiosk"
    assert config.agent.max_steps_per_request == 7


def test_local_override_wins(config_dir: Path) -> None:
    write(config_dir / "models.local.yaml", "llm:\n  model: big-model\n  thinking_level: high\n")
    write(config_dir / "settings.local.yaml", "screen:\n  settle_timeout_s: 1.5\n")
    config = load_config(config_dir)
    assert config.llm.model == "big-model"
    assert config.llm.thinking_level == "high"
    assert config.llm.temperature == 0.5  # kept from the shared file
    assert config.screen.settle_timeout_s == 1.5
    assert config.screen.window_title == "Test Kiosk"


def test_missing_model_is_an_error(config_dir: Path) -> None:
    write(config_dir / "models.yaml", "llm:\n  provider: gemini\n")
    with pytest.raises(ConfigError):
        load_config(config_dir)


def test_unsupported_provider(config_dir: Path) -> None:
    write(config_dir / "models.local.yaml", "llm:\n  provider: ollama\n")
    with pytest.raises(ConfigError, match="provider"):
        load_config(config_dir)


def test_invalid_thinking_level(config_dir: Path) -> None:
    write(config_dir / "models.local.yaml", "llm:\n  thinking_level: extreme\n")
    with pytest.raises(ConfigError, match="thinking_level"):
        load_config(config_dir)


def test_missing_file(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="not found"):
        load_config(tmp_path)


def test_repository_configs_load() -> None:
    config = load_config(CONFIG_DIR)
    assert config.llm.model
    assert config.screen.window_title == "Test Kiosk"
    assert config.agent.payment_button_pattern
    assert config.agent.discard_button_pattern


def test_env_file_sets_missing_variables_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("KIOSK_TEST_KEY", raising=False)
    monkeypatch.setenv("KIOSK_TEST_SET", "from-environment")
    write(
        tmp_path / ".env",
        "# comment\n\nKIOSK_TEST_KEY = 'secret value'\nexport KIOSK_TEST_SET=from-file\nbad line\n",
    )
    loaded = load_env_file(tmp_path / ".env")
    assert loaded == ["KIOSK_TEST_KEY"]
    assert os.environ["KIOSK_TEST_KEY"] == "secret value"
    assert os.environ["KIOSK_TEST_SET"] == "from-environment"  # the environment wins
    monkeypatch.delenv("KIOSK_TEST_KEY")
    assert load_env_file(tmp_path / "missing.env") == []


def test_stt_and_audio_defaults_and_overrides(config_dir: Path) -> None:
    config = load_config(config_dir)
    assert config.stt.thinking_level == "minimal"
    assert config.stt.model != config.llm.model  # its own rate-limit quota
    assert config.audio.sample_rate == 16000
    assert config.audio.device is None
    write(config_dir / "models.local.yaml", "stt:\n  model: other-stt\n  vocabulary_hints: false\n")
    write(config_dir / "settings.local.yaml", "audio:\n  device: USB\n  silence_end_ms: 1000\n")
    config = load_config(config_dir)
    assert (config.stt.model, config.stt.vocabulary_hints) == ("other-stt", False)
    assert (config.audio.device, config.audio.silence_end_ms) == ("USB", 1000)
    llm = config.stt.llm_config("MY_KEY")
    assert (llm.model, llm.api_key_env, llm.thinking_level) == ("other-stt", "MY_KEY", "minimal")


def test_invalid_audio_and_stt_settings(config_dir: Path) -> None:
    write(config_dir / "settings.local.yaml", "audio:\n  frame_ms: 25\n")
    with pytest.raises(ConfigError, match="frame_ms"):
        load_config(config_dir)
    write(config_dir / "settings.local.yaml", "audio:\n  threshold_factor: 0.5\n")
    with pytest.raises(ConfigError, match="threshold_factor"):
        load_config(config_dir)
    (config_dir / "settings.local.yaml").unlink()
    write(config_dir / "models.local.yaml", "stt:\n  thinking_level: none\n")
    with pytest.raises(ConfigError, match="stt.thinking_level"):
        load_config(config_dir)


def test_repository_stt_model_differs_from_the_agent_model() -> None:
    config = load_config(CONFIG_DIR)
    assert config.stt.model != config.llm.model
