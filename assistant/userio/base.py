"""Interfaces between the agent and the user.

The console implements them now; speech recognition (input), TTS and the visual overlay
(output) will implement the same interfaces later. Output is a set of events, not just text,
so the overlay can show the avatar state and images of the kiosk buttons being discussed.

The agent calls these from its worker thread. A Qt implementation must forward the calls to
the GUI thread (e.g. with signals).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from assistant.screen.model import Element


class AssistantState(StrEnum):
    IDLE = "idle"
    LISTENING = "listening"
    THINKING = "thinking"
    ACTING = "acting"  # operating the kiosk
    SPEAKING = "speaking"


@dataclass(frozen=True)
class Choice:
    """One option offered to the user, e.g. a "ICE" button on the kiosk."""

    label: str
    element: Element | None = None  # its rectangle lets the overlay crop the kiosk button


class UserInput(Protocol):
    def listen(self) -> str | None:
        """Wait for the next user message. None means the user is gone (quit)."""
        ...


class UserOutput(Protocol):
    def say(self, text: str) -> None:
        """Tell the user something (no answer needed)."""
        ...

    def ask(self, question: str, choices: Sequence[Choice]) -> None:
        """Ask the user something; `choices` may be empty for open questions."""
        ...

    def show_elements(self, elements: Sequence[Element]) -> None:
        """The kiosk elements the assistant is acting on right now."""
        ...

    def set_state(self, state: AssistantState) -> None:
        """Avatar state: idle, listening, thinking, acting, speaking."""
        ...
