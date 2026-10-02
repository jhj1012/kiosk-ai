"""Console input and output: type Korean in the terminal, read the replies there."""

from __future__ import annotations

import sys
from collections.abc import Sequence

from assistant.screen.model import Element
from assistant.userio.base import AssistantState, Choice

USER_PROMPT = "나> "
AI_PREFIX = "AI> "


class ConsoleInput:
    def listen(self) -> str | None:
        try:
            line = input(USER_PROMPT)
        except EOFError:
            return None
        if not sys.stdin.isatty():
            print(line)  # piped input is not echoed; show it so the transcript reads naturally
        return line


class ConsoleOutput:
    def __init__(self, *, show_states: bool = False) -> None:
        self.show_states = show_states

    def say(self, text: str) -> None:
        print(f"{AI_PREFIX}{text}", flush=True)

    def ask(self, question: str, choices: Sequence[Choice]) -> None:
        print(f"{AI_PREFIX}{question}", flush=True)
        if choices:
            print(f"    (선택지: {' / '.join(c.label for c in choices)})", flush=True)

    def show_elements(self, elements: Sequence[Element]) -> None:
        if elements:
            print(f"    [화면 조작] {' → '.join(e.name for e in elements)}", flush=True)

    def set_state(self, state: AssistantState) -> None:
        if self.show_states:
            print(f"    ({state})", flush=True)
