"""Load `configs/models.yaml` and `configs/settings.yaml` into typed settings.

Each file may have a git-ignored `*.local.yaml` sibling (e.g. `models.local.yaml`) whose
values are merged on top, so a teammate can change the model without touching shared files.
Secrets (the Gemini API key) come from environment variables, or from a git-ignored `.env`
file in the repository root.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = REPO_ROOT / "configs"
ENV_FILE = REPO_ROOT / ".env"
VALID_THINKING_LEVELS = ("minimal", "low", "medium", "high")


class ConfigError(Exception):
    """A config file is missing or has invalid values."""


@dataclass(frozen=True)
class LlmConfig:
    model: str
    provider: str = "gemini"
    api_key_env: str = "GEMINI_API_KEY"  # environment variable that holds the API key
    thinking_level: str = "low"
    temperature: float = 1.0
    max_output_tokens: int = 2048  # includes thinking tokens; stops runaway answers
    timeout_s: float = 30.0


@dataclass(frozen=True)
class SttConfig:
    """Speech recognition: a separate Gemini model, so it has its own rate-limit quota."""

    model: str = "gemini-3.1-flash-lite"
    thinking_level: str = "minimal"
    temperature: float = 1.0
    max_output_tokens: int = 512
    timeout_s: float = 15.0
    vocabulary_hints: bool = True  # tell the model the names on the kiosk screen

    def llm_config(self, api_key_env: str) -> LlmConfig:
        return LlmConfig(
            model=self.model,
            api_key_env=api_key_env,
            thinking_level=self.thinking_level,
            temperature=self.temperature,
            max_output_tokens=self.max_output_tokens,
            timeout_s=self.timeout_s,
        )


@dataclass(frozen=True)
class AudioConfig:
    """Microphone and voice activity detection (levels are RMS of 16-bit samples)."""

    sample_rate: int = 16000
    device: int | str | None = None  # None = Windows default; an index or part of the name
    frame_ms: int = 30
    calibration_s: float = 1.0  # background noise is measured this long at start-up
    threshold_factor: float = 3.0  # speech is this many times louder than the noise
    min_threshold: float = 300.0  # ...and never quieter than this
    start_ms: int = 150  # this much loud audio in a row starts an utterance
    pre_roll_ms: int = 300  # audio kept from before the start, so no syllable is cut
    silence_end_ms: int = 800  # this much quiet ends the utterance
    min_utterance_ms: int = 300  # less loud audio than this is a cough or a click: dropped
    max_utterance_s: float = 15.0  # longer utterances are cut here
    echo_tail_ms: int = 300  # after the assistant stops speaking, keep ignoring the mic


@dataclass(frozen=True)
class ScreenConfig:
    window_title: str
    settle_timeout_s: float = 5.0
    poll_interval_s: float = 0.1


@dataclass(frozen=True)
class AgentConfig:
    max_steps_per_request: int = 10
    history_turns: int = 10
    new_customer_after_s: float = 30.0
    abandoned_after_s: float = 180.0
    confirm_before_payment: bool = True
    payment_button_pattern: str = r"^(결제|결제 요청|pay)$"
    discard_button_pattern: str = ""


@dataclass(frozen=True)
class Config:
    llm: LlmConfig
    screen: ScreenConfig
    agent: AgentConfig
    stt: SttConfig = SttConfig()
    audio: AudioConfig = AudioConfig()


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
    if llm.provider != "gemini":
        raise ConfigError(f"models.yaml: llm.provider {llm.provider!r} is not supported (gemini)")
    stt = _build(SttConfig, models.get("stt", {}), "models.yaml: stt")
    for where, level in (("llm", llm.thinking_level), ("stt", stt.thinking_level)):
        if level not in VALID_THINKING_LEVELS:
            raise ConfigError(
                f"models.yaml: {where}.thinking_level must be one of "
                f"{', '.join(VALID_THINKING_LEVELS)}"
            )
    screen_values = {
        "window_title": settings.get("target_window", {}).get("title"),
        **settings.get("screen", {}),
    }
    screen = _build(ScreenConfig, screen_values, "settings.yaml: screen/target_window")
    agent = _build(AgentConfig, settings.get("agent", {}), "settings.yaml: agent")
    if agent.max_steps_per_request < 1:
        raise ConfigError("settings.yaml: agent.max_steps_per_request must be at least 1")
    audio = _build(AudioConfig, settings.get("audio", {}), "settings.yaml: audio")
    _check_audio(audio)
    return Config(llm=llm, screen=screen, agent=agent, stt=stt, audio=audio)


def load_env_file(path: Path = ENV_FILE) -> list[str]:
    """Set environment variables from `KEY=value` lines in `path`, if the file exists.

    Variables that are already set win. Returns the names that were set (never the values).
    """
    if not path.exists():
        return []
    loaded = []
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = (part.strip() for part in line.split("=", 1))
        key = key.removeprefix("export ").strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if key and key not in os.environ:
            os.environ[key] = value
            loaded.append(key)
    return loaded


def _check_audio(audio: AudioConfig) -> None:
    if audio.sample_rate < 8000 or audio.frame_ms not in (10, 20, 30):
        raise ConfigError("settings.yaml: audio needs sample_rate >= 8000 and frame_ms 10/20/30")
    if audio.calibration_s <= 0 or audio.max_utterance_s <= 0 or audio.silence_end_ms <= 0:
        raise ConfigError("settings.yaml: audio times must be positive")
    if audio.threshold_factor < 1:
        raise ConfigError("settings.yaml: audio.threshold_factor must be at least 1")


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
