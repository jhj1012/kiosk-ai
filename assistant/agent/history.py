"""The conversation sent to the model.

Only the latest screen is ever in the context: it is added as the last message of each
request and never stored. This keeps the prompt short and keeps the stored history a stable
prefix, which Ollama can reuse between requests (prompt caching).
"""

from __future__ import annotations

from assistant.llm.client import Message
from assistant.llm.prompts import customer_message, screen_message


class Conversation:
    def __init__(self, system_prompt: str, max_messages: int) -> None:
        self.system_prompt = system_prompt
        self.max_messages = max_messages
        self._messages: list[Message] = []
        self._turn_starts: list[int] = []  # indexes of customer messages

    def clear(self) -> None:
        self._messages.clear()
        self._turn_starts.clear()

    def add_customer(self, text: str) -> None:
        self._turn_starts.append(len(self._messages))
        self._messages.append({"role": "user", "content": customer_message(text)})
        self._trim()

    def add_model(self, text: str) -> None:
        self._messages.append({"role": "assistant", "content": text})

    def add_note(self, text: str) -> None:
        """Action results and errors for the model (not from the customer)."""
        self._messages.append({"role": "user", "content": text})

    def build(self, screen_text: str, extra_note: str | None = None) -> list[Message]:
        """Messages for one request: system prompt, history, then the current screen."""
        messages: list[Message] = [{"role": "system", "content": self.system_prompt}]
        messages.extend(self._messages)
        if extra_note:
            messages.append({"role": "user", "content": extra_note})
        messages.append({"role": "user", "content": screen_message(screen_text)})
        return messages

    @property
    def messages(self) -> list[Message]:
        return list(self._messages)

    def _trim(self) -> None:
        """Drop the oldest turns (whole turns only) while the history is too long.

        The current turn is always kept, even if it alone is longer than the limit.
        """
        while len(self._messages) > self.max_messages and len(self._turn_starts) > 1:
            cut = self._turn_starts[1]
            del self._messages[:cut]
            self._turn_starts = [i - cut for i in self._turn_starts[1:]]
