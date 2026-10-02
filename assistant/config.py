"""Load `configs/models.yaml` and `configs/settings.yaml` into typed settings.

Each file may have a git-ignored `*.local.yaml` sibling (e.g. `models.local.yaml`) whose
values are merged on top, so a teammate can change the model without touching shared files.
"""

from __future__ import annotations

from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any

import yaml

CONFIG_DIR = Path(__file__).resolve().parent.parent / "configs"


class ConfigError(Exception):
    """A config file is missing or has invalid values."""


@dataclass(frozen=True)
class LlmConfig:
    model: str
    provider: str = "ollama"
    host: str = "http://localhost:11434"
    temperature: float = 0.0
    num_ctx: int = 8192
    num_predict: int = 400
    keep_alive: str = "30m"
    timeout_s: float = 120.0


@dataclass(frozen=True)
class ScreenConfig:
    window_title: str
    settle_timeout_s: float = 5.0
    poll_interval_s: float = 0.1


@dataclass(frozen=True)
class AgentConfig:
    max_steps_per_request: int = 10
    history_turns: int = 10
    confirm_before_payment: bool = True
    payment_button_pattern: str = r"^(결제|결제 요청|pay)$"
    discard_button_pattern: str = ""


@dataclass(frozen=True)
class Config:
    llm: LlmConfig
    screen: ScreenConfig
    agent: AgentConfig


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Return `base` updated with `override`; nested dicts are merged key by key."""
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_yaml(path: Path) -> dict[str, Any]:
    """Read `path` and merge its `*.local.yaml` sibling on top, if it exists."""
    data = _read_yaml(path)
    local = path.with_name(f"{path.stem}.local{path.suffix}")
    if local.exists():
        data = deep_merge(data, _read_yaml(local))
    return data


def load_config(config_dir: Path = CONFIG_DIR) -> Config:
    models = load_yaml(config_dir / "models.yaml")
    settings = load_yaml(config_dir / "settings.yaml")

    llm = _build(LlmConfig, models.get("llm", {}), "models.yaml: llm")
    if llm.provider != "ollama":
        raise ConfigError(f"models.yaml: llm.provider {llm.provider!r} is not supported (ollama)")
    screen_values = {
        "window_title": settings.get("target_window", {}).get("title"),
        **settings.get("screen", {}),
    }
    screen = _build(ScreenConfig, screen_values, "settings.yaml: screen/target_window")
    agent = _build(AgentConfig, settings.get("agent", {}), "settings.yaml: agent")
    if agent.max_steps_per_request < 1:
        raise ConfigError("settings.yaml: agent.max_steps_per_request must be at least 1")
    return Config(llm=llm, screen=screen, agent=agent)


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ConfigError(f"config file not found: {path}")
    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ConfigError(f"{path} must contain a mapping at the top level")
    return data


def _build[T](cls: type[T], values: dict[str, Any], where: str) -> T:
    """Create a config dataclass from `values`, ignoring keys it does not know."""
    known = {f.name for f in fields(cls)}  # type: ignore[arg-type]
    try:
        return cls(**{k: v for k, v in values.items() if k in known and v is not None})
    except TypeError as e:
        raise ConfigError(f"{where}: {e}") from e
