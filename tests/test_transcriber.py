"""Transcription prompt, answer parsing and non-speech filtering (no Gemini API)."""

from __future__ import annotations

import json
from typing import Any

import pytest

from assistant.llm.client import ChatResult, LlmError
from assistant.screen.reader import build_snapshot
from assistant.stt.transcriber import (
    HINTS_INTRO,
    TRANSCRIPT_SCHEMA,
    GeminiTranscriber,
    build_prompt,
    parse_transcript,
    vocabulary,
)
from tests.screen_fakes import button, check, text, window


class FakeAudioModel:
    def __init__(self, *answers: dict[str, Any] | str | Exception) -> None:
        self.answers = list(answers)
        self.calls: list[tuple[str, bytes, str, dict[str, Any]]] = []

    def audio_json(
        self, prompt: str, audio: bytes, mime_type: str, schema: dict[str, Any]
    ) -> ChatResult:
        self.calls.append((prompt, audio, mime_type, schema))
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        body = answer if isinstance(answer, str) else json.dumps(answer, ensure_ascii=False)
        return ChatResult(text=body, seconds=1.2)


def test_speech_is_returned_cleaned() -> None:
    t = parse_transcript(
        '{"sounds": "a man", "speech": true, "text": " 아이스  아메리카노\\n주세요 "}'
    )
    assert t.heard
    assert t.text == "아이스 아메리카노 주세요"


@pytest.mark.parametrize(
    "answer",
    [
        '{"sounds": "silence", "speech": false, "text": ""}',
        '{"sounds": "noise", "speech": false, "text": "아메리카노"}',  # text without speech
        '{"sounds": "a click", "speech": true, "text": ""}',
        '{"sounds": "?", "speech": true, "text": "..."}',  # punctuation only
        '{"speech": "yes", "text": "네"}',  # not a boolean
        "not json",
        "[1, 2]",
    ],
)
def test_non_speech_and_broken_answers_are_ignored(answer: str) -> None:
    assert not parse_transcript(answer).heard


def test_short_answers_and_numbers_count() -> None:
    assert parse_transcript('{"speech": true, "text": "네"}').text == "네"
    assert parse_transcript('{"speech": true, "text": "2"}').heard


def test_vocabulary_drops_prices_and_state() -> None:
    snapshot = build_snapshot(
        window(
            text("옵션 선택"),
            button("아이스 아메리카노 2,000원"),
            check("온도 ICE +0원 (선택됨)", on=True),
            check("사이즈 Large +500원"),
            text("수량 1개"),
            button("+"),
            button("아이스 아메리카노 2,000원"),
        ),
        "Test",
    )
    words = vocabulary(snapshot)
    assert "아이스 아메리카노" in words
    assert "온도 ICE" in words
    assert "사이즈 Large" in words
    assert "+" not in words
    assert words.count("아이스 아메리카노") == 1


def test_prompt_with_and_without_hints() -> None:
    assert HINTS_INTRO not in build_prompt()
    prompt = build_prompt(["할메가커피", "아인슈페너"])
    assert prompt.endswith("할메가커피, 아인슈페너")
    assert "NOT what was said" in prompt


def test_transcriber_sends_wav_with_schema_and_hints() -> None:
    model = FakeAudioModel({"sounds": "speech", "speech": True, "text": "할메가커피 두 잔"})
    transcript = GeminiTranscriber(model).transcribe(b"RIFF....", ["할메가커피"])
    assert transcript.text == "할메가커피 두 잔"
    assert transcript.seconds == 1.2
    prompt, audio, mime_type, schema = model.calls[0]
    assert (audio, mime_type, schema) == (b"RIFF....", "audio/wav", TRANSCRIPT_SCHEMA)
    assert "할메가커피" in prompt


def test_transcriber_passes_api_errors_on() -> None:
    with pytest.raises(LlmError):
        GeminiTranscriber(FakeAudioModel(LlmError("503"))).transcribe(b"")


def test_schema_uses_only_gemini_keywords() -> None:
    allowed = {"type", "properties", "required", "description", "propertyOrdering"}
    assert set(TRANSCRIPT_SCHEMA) <= allowed
    for prop in TRANSCRIPT_SCHEMA["properties"].values():
        assert set(prop) <= {"type", "description"}
