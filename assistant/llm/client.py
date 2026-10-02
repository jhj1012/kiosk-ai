"""Chat model interface and the Gemini API implementation.

Answers are requested as JSON constrained by a schema (Gemini structured output), so they
always parse and targets can be limited to the controls on the current screen.
"""

from __future__ import annotations

import logging
import os
import re
import time
from dataclasses import dataclass
from typing import Any, Protocol

from assistant.config import LlmConfig

log = logging.getLogger(__name__)

Message = dict[str, str]  # {"role": "system" | "user" | "assistant", "content": text}

RETRY_CODES = {429, 500, 502, 503, 504}  # rate limit and temporary server errors
RETRY_DELAYS_S = (1.0, 3.0)
MAX_RETRY_WAIT_S = 60.0  # longer waits (e.g. a daily quota) fail at once


class LlmError(Exception):
    """The model could not be reached or did not answer."""


@dataclass(frozen=True)
class ChatResult:
    text: str
    seconds: float = 0.0
    prompt_tokens: int = 0
    output_tokens: int = 0
    finish_reason: str = ""  # "STOP", or "MAX_TOKENS" if the answer was cut off


class ChatModel(Protocol):
    def chat_json(self, messages: list[Message], schema: dict[str, Any]) -> ChatResult:
        """Send the conversation; the answer is JSON that follows `schema`."""
        ...


def to_gemini(messages: list[Message]) -> tuple[str, list[dict[str, Any]]]:
    """Split messages into Gemini's system instruction and contents.

    Gemini calls the assistant role "model". Consecutive messages of the same role (e.g. a
    customer message followed by the screen) are joined into one turn.
    """
    system = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
    contents: list[dict[str, Any]] = []
    for m in messages:
        if m["role"] == "system":
            continue
        role = "model" if m["role"] == "assistant" else "user"
        if contents and contents[-1]["role"] == role:
            contents[-1]["parts"].append({"text": m["content"]})
        else:
            contents.append({"role": role, "parts": [{"text": m["content"]}]})
    return system, contents


class GeminiChatModel:
    def __init__(self, config: LlmConfig, client: Any = None) -> None:
        """`client` is for tests; normally a google-genai client is created here."""
        self.config = config
        if client is None:
            api_key = os.environ.get(config.api_key_env, "").strip()
            if not api_key:
                raise LlmError(
                    f"No Gemini API key: set {config.api_key_env} in your environment or in "
                    "the .env file (see docs/setup.md)."
                )
            from google import genai  # imported here so tests and CI do not need the package

            client = genai.Client(
                api_key=api_key, http_options={"timeout": int(config.timeout_s * 1000)}
            )
        self._client = client

    def check_ready(self) -> None:
        """Fail early with a clear message if the key or the model name is wrong."""
        try:
            self._client.models.get(model=self.config.model)
        except Exception as e:
            code = getattr(e, "code", None)
            hint = {
                400: "the API key looks invalid",
                401: "the API key is invalid",
                403: "the API key has no access to this model",
                404: f"model {self.config.model!r} does not exist",
            }.get(code, "check your internet connection")
            raise LlmError(f"Gemini API check failed ({hint}): {e}") from e

    def chat_json(self, messages: list[Message], schema: dict[str, Any]) -> ChatResult:
        system, contents = to_gemini(messages)
        config = {
            "system_instruction": system or None,
            "temperature": self.config.temperature,
            "max_output_tokens": self.config.max_output_tokens,
            "response_mime_type": "application/json",
            "response_json_schema": schema,
            "thinking_config": {"thinking_level": self.config.thinking_level.upper()},
            "automatic_function_calling": {"disable": True},  # no tools; silences an SDK warning
        }
        start = time.monotonic()
        response = self._generate(contents, config)
        usage = getattr(response, "usage_metadata", None)
        candidates = getattr(response, "candidates", None) or []
        finish = getattr(candidates[0], "finish_reason", "") if candidates else ""
        result = ChatResult(
            text=response.text or "",
            seconds=time.monotonic() - start,
            prompt_tokens=getattr(usage, "prompt_token_count", 0) or 0,
            output_tokens=getattr(usage, "candidates_token_count", 0) or 0,
            finish_reason=str(getattr(finish, "name", finish) or ""),
        )
        log.info(
            "llm %.1fs, prompt %d tokens, output %d tokens, thinking %d tokens (%s)",
            result.seconds,
            result.prompt_tokens,
            result.output_tokens,
            getattr(usage, "thoughts_token_count", 0) or 0,
            result.finish_reason,
        )
        return result

    def _generate(self, contents: list[dict[str, Any]], config: dict[str, Any]) -> Any:
        """Call the API, retrying rate limits and temporary server errors."""
        for attempt in range(len(RETRY_DELAYS_S) + 1):
            try:
                return self._client.models.generate_content(
                    model=self.config.model, contents=contents, config=config
                )
            except Exception as e:  # google.genai.errors.APIError, network errors, timeouts
                code = getattr(e, "code", None)
                if code in RETRY_CODES and attempt < len(RETRY_DELAYS_S):
                    # Rate limits say how long to wait ("retryDelay": "31s"), e.g. the free
                    # tier's requests-per-minute limit; otherwise back off briefly.
                    delay = retry_delay(e) or RETRY_DELAYS_S[attempt]
                    if delay > MAX_RETRY_WAIT_S:
                        raise LlmError(f"Gemini API request failed: {e}") from e
                    log.warning("Gemini API error %s, retrying in %.0f s: %s", code, delay, e)
                    time.sleep(delay)
                    continue
                raise LlmError(f"Gemini API request failed: {e}") from e
        raise AssertionError("unreachable")


def retry_delay(error: Exception) -> float | None:
    """The wait a rate-limit error asks for, from its "retryDelay" field, if any."""
    match = re.search(r"retryDelay['\"]?\s*:\s*['\"](\d+(?:\.\d+)?)s", str(error))
    return float(match.group(1)) + 1 if match else None
