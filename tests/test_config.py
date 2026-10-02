"""Tests for config loading and *.local.yaml overrides."""

from pathlib import Path

import pytest

from assistant.config import CONFIG_DIR, ConfigError, deep_merge, load_config


def write(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


@pytest.fixture
def config_dir(tmp_path: Path) -> Path:
    write(
        tmp_path / "models.yaml",
        "llm:\n  provider: ollama\n  model: base-model\n  temperature: 0.0\nstt:\n  model: large\n",
    )
    write(
        tmp_path / "settings.yaml",
        'target_window:\n  title: "Test Kiosk"\n'
        "agent:\n  max_steps_per_request: 7\n  confirm_before_payment: true\n",
    )
    return tmp_path


def test_deep_merge_merges_nested_dicts() -> None:
    base = {"llm": {"model": "a", "host": "h"}, "x": 1}
    merged = deep_merge(base, {"llm": {"model": "b"}, "y": 2})
    assert merged == {"llm": {"model": "b", "host": "h"}, "x": 1, "y": 2}
    assert base["llm"]["model"] == "a"  # input not modified


def test_load_config_without_local_files(config_dir: Path) -> None:
    config = load_config(config_dir)
    assert config.llm.model == "base-model"
    assert config.llm.num_predict == 400  # default
    assert config.screen.window_title == "Test Kiosk"
    assert config.agent.max_steps_per_request == 7


def test_local_override_wins(config_dir: Path) -> None:
    write(config_dir / "models.local.yaml", "llm:\n  model: big-model\n  num_ctx: 4096\n")
    write(config_dir / "settings.local.yaml", "screen:\n  settle_timeout_s: 1.5\n")
    config = load_config(config_dir)
    assert config.llm.model == "big-model"
    assert config.llm.num_ctx == 4096
    assert config.llm.temperature == 0.0  # kept from the shared file
    assert config.screen.settle_timeout_s == 1.5
    assert config.screen.window_title == "Test Kiosk"


def test_missing_model_is_an_error(config_dir: Path) -> None:
    write(config_dir / "models.yaml", "llm:\n  provider: ollama\n")
    with pytest.raises(ConfigError):
        load_config(config_dir)


def test_unsupported_provider(config_dir: Path) -> None:
    write(config_dir / "models.local.yaml", "llm:\n  provider: cloud\n")
    with pytest.raises(ConfigError, match="provider"):
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
