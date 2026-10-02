"""Chat model interface and the Ollama implementation.

Answers are requested as JSON constrained by a schema (Ollama structured outputs), so they
always parse and element numbers can be limited to the ones on the current screen.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Protocol

from assistant.config import LlmConfig

log = logging.getLogger(__name__)

Message = dict[str, str]


class LlmError(Exception):
    """The model could not be reached or did not answer."""


@dataclass(frozen=True)
class ChatResult:
    text: str
    seconds: float = 0.0
    prompt_tokens: int = 0
    output_tokens: int = 0
    done_reason: str = ""  # "stop", or "length" if num_predict cut the answer off


class ChatModel(Protocol):
    def chat_json(self, messages: list[Message], schema: dict[str, Any]) -> ChatResult:
        """Send the conversation; the answer is JSON that follows `schema`."""
        ...


class OllamaChatModel:
    def __init__(self, config: LlmConfig) -> None:
        import ollama  # imported here so tests and CI do not need the package

        self.config = config
        self._ollama = ollama
        self._client = ollama.Client(host=config.host, timeout=config.timeout_s)

    def check_ready(self) -> None:
        """Fail early with a clear message if Ollama is down or the model is not pulled."""
        model = self.config.model
        try:
            names = {m.model for m in self._client.list().models}
        except Exception as e:  # connection refused, timeout, ...
            raise LlmError(
                f"Ollama is not reachable at {self.config.host} ({e}). "
                "Start Ollama (tray app or `ollama serve`)."
            ) from e
        if model not in names:
            raise LlmError(f"Model {model!r} is not pulled. Run: ollama pull {model}")

    def warm_up(self) -> None:
        """Load the model into memory now, so the first request is not slow."""
        try:
            self._client.generate(model=self.config.model, prompt="", keep_alive=self._keep_alive)
        except Exception as e:
            raise LlmError(f"Could not load {self.config.model}: {e}") from e

    def chat_json(self, messages: list[Message], schema: dict[str, Any]) -> ChatResult:
        start = time.monotonic()
        try:
            response = self._client.chat(
                model=self.config.model,
                messages=messages,
                format=schema,
                options={
                    "temperature": self.config.temperature,
                    "num_ctx": self.config.num_ctx,
                    "num_predict": self.config.num_predict,
                },
                keep_alive=self._keep_alive,
            )
        except Exception as e:  # ollama.ResponseError, connection errors, timeouts
            raise LlmError(f"Ollama request failed: {e}") from e
        result = ChatResult(
            text=response.message.content or "",
            seconds=time.monotonic() - start,
            prompt_tokens=response.prompt_eval_count or 0,
            output_tokens=response.eval_count or 0,
            done_reason=response.done_reason or "",
        )
        log.info(
            "llm %.1fs, prompt %d tokens, output %d tokens (%s)",
            result.seconds,
            result.prompt_tokens,
            result.output_tokens,
            result.done_reason,
        )
        return result

    @property
    def _keep_alive(self) -> str | float:
        value = self.config.keep_alive
        return float(value) if isinstance(value, int | float) else value
