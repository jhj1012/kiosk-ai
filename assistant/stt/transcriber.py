"""Korean speech recognition with the Gemini API (audio input, structured JSON output).

The model answers `{"speech": bool, "text": str}`, so noise, coughs and silence (which a
model may otherwise "transcribe") are filtered out before the agent sees anything.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from assistant.llm.client import ChatResult
from assistant.screen.model import Snapshot

log = logging.getLogger(__name__)

TRANSCRIPT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "sounds": {
            "type": "string",
            "description": "first, a few English words on what is audible, e.g. 'silence', "
            "'a beep', 'clattering', 'a woman speaking Korean'",
        },
        "speech": {
            "type": "boolean",
            "description": "true only if a person clearly says words in the recording",
        },
        "text": {
            "type": "string",
            "description": "exactly the words that were said; empty if speech is false",
        },
    },
    "required": ["sounds", "speech", "text"],
    "propertyOrdering": ["sounds", "speech", "text"],
}

PROMPT = """\
Transcribe this recording from a microphone, if a person speaks in it. The language is \
usually Korean; write Korean in Hangul.

Many recordings contain no speech: only silence, a tone or beep, noise, music, a cough, a \
click, breathing or clattering. Then "speech" is false and "text" is "". Speech that is too \
faint or unclear to understand also counts as no speech.

If there is speech, write exactly the words that are said. Do not answer, translate, correct, \
summarize or add words, and never guess words that are not clearly audible."""

HINTS_INTRO = (
    "\n\nSpelling list: names that may come up. They are NOT what was said; use them only to "
    "spell a name that is clearly said. Without audible words the answer is speech false, "
    "whatever this list contains.\n"
)
MAX_HINTS = 80
MAX_HINT_CHARS = 30
# Parts of control names that are not words a customer says: prices, state, counts.
_NOISE = re.compile(r"\(선택됨\)|[+−-]?\d[\d,]*\s*원|\d+\s*개|\s+")
_LETTER = re.compile(r"[가-힣A-Za-z]")


class AudioModel(Protocol):
    def audio_json(
        self, prompt: str, audio: bytes, mime_type: str, schema: dict[str, Any]
    ) -> ChatResult: ...


@dataclass(frozen=True)
class Transcript:
    text: str
    speech: bool
    seconds: float = 0.0  # time the API took

    @property
    def heard(self) -> bool:
        """Speech with words: the agent should get it."""
        return self.speech and bool(self.text)


def parse_transcript(answer: str, seconds: float = 0.0) -> Transcript:
    """The model's JSON answer as a Transcript; anything unusable counts as no speech."""
    try:
        data = json.loads(answer)
    except json.JSONDecodeError:
        log.warning("unreadable transcription answer: %r", answer[:200])
        return Transcript("", False, seconds)
    if not isinstance(data, dict):
        return Transcript("", False, seconds)
    text = data.get("text")
    text = " ".join(text.split()) if isinstance(text, str) else ""
    if not _LETTER.search(text) and not any(c.isdigit() for c in text):
        text = ""  # only punctuation or symbols ("...", "-")
    return Transcript(text, data.get("speech") is True and bool(text), seconds)


def vocabulary(snapshot: Snapshot) -> list[str]:
    """Names on the screen a customer may say ("아이스 아메리카노"), without prices or state."""
    words: list[str] = []
    for element in snapshot.elements:
        name = _NOISE.sub(" ", element.name).strip()
        if _LETTER.search(name) and len(name) <= MAX_HINT_CHARS and name not in words:
            words.append(name)
    return words[:MAX_HINTS]


def build_prompt(hints: Iterable[str] = ()) -> str:
    hints = [h for h in hints if h][:MAX_HINTS]
    if not hints:
        return PROMPT
    return PROMPT + HINTS_INTRO + ", ".join(hints)


class GeminiTranscriber:
    def __init__(self, model: AudioModel) -> None:
        self.model = model

    def transcribe(self, wav: bytes, hints: Sequence[str] = ()) -> Transcript:
        """Transcribe one WAV utterance. Raises LlmError if the API fails."""
        prompt = build_prompt(hints)
        result = self.model.audio_json(prompt, wav, "audio/wav", TRANSCRIPT_SCHEMA)
        transcript = parse_transcript(result.text, result.seconds)
        log.debug("transcription answer: %s", result.text)
        return transcript
