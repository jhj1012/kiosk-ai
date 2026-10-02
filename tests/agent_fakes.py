"""Fakes for agent tests: a scripted screen, a scripted LLM and a recording output."""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from typing import Any

from assistant.config import AgentConfig, ScreenConfig
from assistant.llm.client import ChatResult, LlmError, Message
from assistant.screen.base import ActionError, ScrollDirection
from assistant.screen.model import Element, Snapshot
from assistant.screen.reader import RawNode, build_snapshot
from assistant.userio.base import AssistantState, Choice

FAST_SCREEN = ScreenConfig(window_title="Test", settle_timeout_s=0.05, poll_interval_s=0.0)


def agent_config(**overrides: Any) -> AgentConfig:
    values: dict[str, Any] = {
        "max_steps_per_request": 4,
        "payment_button_pattern": "^결제$",
        "discard_button_pattern": "^처음으로$",
    }
    values.update(overrides)
    return AgentConfig(**values)


class FakeScreen:
    """Shows one RawNode page at a time; button presses can switch pages via `on_press`."""

    def __init__(self, page: RawNode) -> None:
        self.page = page
        self.on_press: dict[str, Callable[[], None]] = {}
        self.calls: list[tuple[str, str]] = []
        self.fail_read: Exception | None = None

    def read(self) -> Snapshot:
        if self.fail_read is not None:
            raise self.fail_read
        return build_snapshot(self.page, "Test")

    def invoke(self, element: Element) -> None:
        self._node(element)
        self.calls.append(("invoke", element.name))
        handler = self.on_press.get(element.name)
        if handler is not None:
            handler()

    def toggle(self, element: Element) -> None:
        node = self._node(element)
        node.toggle_state = not node.toggle_state
        self.calls.append(("toggle", element.name))

    def select(self, element: Element) -> None:
        self._node(element)
        self.calls.append(("select", element.name))

    def set_value(self, element: Element, text: str) -> None:
        self._node(element).value = text
        self.calls.append(("set_value", text))

    def scroll(self, region: Element, direction: ScrollDirection) -> None:
        self.calls.append(("scroll", direction))

    def click(self, element: Element) -> None:
        self._node(element)
        self.calls.append(("click", element.name))

    def _node(self, element: Element) -> RawNode:
        stack = [self.page]
        while stack:
            node = stack.pop()
            if node.runtime_id == element.runtime_id:
                return node
            stack.extend(node.children)
        raise ActionError(f"{element.label} is no longer on the screen")


class FakeLlm:
    """Returns scripted answers in order and records every request."""

    def __init__(self, *answers: dict[str, Any] | str | Exception) -> None:
        self.answers = list(answers)
        self.requests: list[tuple[list[Message], dict[str, Any]]] = []

    def chat_json(self, messages: list[Message], schema: dict[str, Any]) -> ChatResult:
        self.requests.append((messages, schema))
        if not self.answers:
            raise AssertionError("the agent asked the LLM more often than scripted")
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        text = answer if isinstance(answer, str) else json.dumps(answer, ensure_ascii=False)
        return ChatResult(text=text)


class RecordingOutput:
    def __init__(self) -> None:
        self.events: list[tuple[str, Any]] = []

    def say(self, text: str) -> None:
        self.events.append(("say", text))

    def ask(self, question: str, choices: Sequence[Choice]) -> None:
        self.events.append(("ask", (question, [c.label for c in choices])))

    def show_elements(self, elements: Sequence[Element]) -> None:
        self.events.append(("show", [e.name for e in elements]))

    def set_state(self, state: AssistantState) -> None:
        self.events.append(("state", state))

    @property
    def messages(self) -> list[tuple[str, Any]]:
        """say/ask events only."""
        return [e for e in self.events if e[0] in ("say", "ask")]


def act(*actions: dict[str, Any], thought: str = "t") -> dict[str, Any]:
    return {"screen": "s", "todo": thought, "next": "act", "actions": list(actions)}


def reply(message: str, kind: str = "ask", choices: list[int] | None = None) -> dict[str, Any]:
    return {
        "screen": "s",
        "next": "reply",
        "kind": kind,
        "message": message,
        "choices": choices or [],
    }


def click(ref: int, times: int = 1) -> dict[str, Any]:
    return {"do": "click", "id": ref, "times": times}


LLM_DOWN = LlmError("connection refused")
