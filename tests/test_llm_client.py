"""Tests for the Gemini client with a fake SDK client (no network, no google-genai needed)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from assistant.config import LlmConfig
from assistant.llm import client as client_module
from assistant.llm.client import GeminiChatModel, LlmError, to_gemini

CONFIG = LlmConfig(model="gemini-test", thinking_level="low", max_output_tokens=512)


class ApiError(Exception):
    def __init__(self, code: int) -> None:
        super().__init__(f"error {code}")
        self.code = code


class FakeModels:
    def __init__(self, *results: Any) -> None:
        self.results = list(results)
        self.calls: list[dict[str, Any]] = []

    def generate_content(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    def get(self, *, model: str) -> Any:
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


def response(text: str) -> Any:
    usage = SimpleNamespace(
        prompt_token_count=100, candidates_token_count=20, thoughts_token_count=5
    )
    finish = SimpleNamespace(name="STOP")
    return SimpleNamespace(
        text=text, usage_metadata=usage, candidates=[SimpleNamespace(finish_reason=finish)]
    )


def model_with(*results: Any) -> tuple[GeminiChatModel, FakeModels]:
    models = FakeModels(*results)
    return GeminiChatModel(CONFIG, client=SimpleNamespace(models=models)), models


def test_to_gemini_splits_system_and_merges_roles() -> None:
    system, contents = to_gemini(
        [
            {"role": "system", "content": "rules"},
            {"role": "user", "content": 'Customer: "hi"'},
            {"role": "user", "content": "CURRENT SCREEN:\n..."},
            {"role": "assistant", "content": "{}"},
            {"role": "user", "content": "RESULT"},
        ]
    )
    assert system == "rules"
    assert contents == [
        {"role": "user", "parts": [{"text": 'Customer: "hi"'}, {"text": "CURRENT SCREEN:\n..."}]},
        {"role": "model", "parts": [{"text": "{}"}]},
        {"role": "user", "parts": [{"text": "RESULT"}]},
    ]


def test_chat_json_sends_schema_and_settings() -> None:
    llm, models = model_with(response('{"next": "reply"}'))
    schema = {"type": "object", "properties": {}}
    result = llm.chat_json(
        [{"role": "system", "content": "rules"}, {"role": "user", "content": "hello"}], schema
    )
    assert result.text == '{"next": "reply"}'
    assert (result.prompt_tokens, result.output_tokens, result.finish_reason) == (100, 20, "STOP")
    call = models.calls[0]
    assert call["model"] == "gemini-test"
    config = call["config"]
    assert config["system_instruction"] == "rules"
    assert config["response_mime_type"] == "application/json"
    assert config["response_json_schema"] is schema
    assert config["max_output_tokens"] == 512
    assert config["thinking_config"] == {"thinking_level": "LOW"}


def test_temporary_errors_are_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(client_module.time, "sleep", lambda s: None)
    llm, models = model_with(ApiError(429), ApiError(503), response("{}"))
    assert llm.chat_json([{"role": "user", "content": "x"}], {}).text == "{}"
    assert len(models.calls) == 3


def test_other_errors_become_llm_errors() -> None:
    llm, _ = model_with(ApiError(400))
    with pytest.raises(LlmError, match="request failed"):
        llm.chat_json([{"role": "user", "content": "x"}], {})


def test_check_ready_explains_the_problem() -> None:
    llm, _ = model_with(ApiError(404))
    with pytest.raises(LlmError, match="does not exist"):
        llm.check_ready()
    llm, _ = model_with(SimpleNamespace(name="models/gemini-test"))
    llm.check_ready()


def test_missing_api_key_is_a_clear_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(LlmError, match="GEMINI_API_KEY"):
        GeminiChatModel(CONFIG)
