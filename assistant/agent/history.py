"""The conversation sent to the model.

Only the latest screen is ever in the context: it is added as the last message of each
request and never stored. Finished turns are condensed to what the customer said and what the
assistant answered; the actions and results in between are kept only for the current turn.
This keeps the prompt short and cheap (long contexts made answers worse in tests) and keeps
the stored history a stable prefix, which the API can reuse between requests (prompt caching).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from assistant.llm.client import Message
from assistant.llm.prompts import customer_message, screen_message


@dataclass
class _Turn:
    customer: str
    steps: list[Message] = field(default_factory=list)  # model answers and action results
    reply: str | None = None  # compact JSON of the final reply, once the turn is over


class Conversation:
    def __init__(self, system_prompt: str, max_turns: int) -> None:
        self.system_prompt = system_prompt
        self.max_turns = max_turns
        self._turns: list[_Turn] = []
        self._paid_in: _Turn | None = None  # the turn in which the last payment was made
        # What this customer has decided so far, as the model last listed it. Shown with every
        # request, because finished turns are condensed and their notes are not sent again.
        self.customer_said: tuple[str, ...] = ()

    def clear(self) -> None:
        self._turns.clear()
        self._paid_in = None
        self.customer_said = ()

    @property
    def is_empty(self) -> bool:
        return not self._turns

    def mark_payment(self) -> None:
        """A payment was made in the current turn: its request to pay is used up."""
        if self._turns:
            self._paid_in = self._turns[-1]

    def add_customer(self, text: str) -> None:
        """Start a new turn; the oldest turns are dropped beyond `max_turns`."""
        self._turns.append(_Turn(text))
        del self._turns[: -self.max_turns]

    def add_model(self, text: str) -> None:
        self._current().steps.append({"role": "assistant", "content": text})

    def add_note(self, text: str) -> None:
        """Action results and errors for the model (not from the customer)."""
        self._current().steps.append({"role": "user", "content": text})

    def end_turn(self, kind: str, message: str) -> None:
        """Record the message that ended the turn; its steps are not sent any more."""
        if self._turns:
            reply = {"next": "reply", "kind": kind, "message": message}
            self._turns[-1].reply = json.dumps(reply, ensure_ascii=False)

    def build(self, screen_text: str, extra_note: str | None = None) -> list[Message]:
        """Messages for one request: system prompt, history, then the current screen."""
        messages: list[Message] = [{"role": "system", "content": self.system_prompt}]
        messages.extend(self.messages)
        if self.customer_said:
            known = "; ".join(self.customer_said)
            messages.append({"role": "user", "content": f"THE CUSTOMER ALREADY DECIDED: {known}"})
        if extra_note:
            messages.append({"role": "user", "content": extra_note})
        messages.append({"role": "user", "content": screen_message(screen_text)})
        return messages

    @property
    def messages(self) -> list[Message]:
        """The history as sent: finished turns condensed, the current turn in full."""
        messages: list[Message] = []
        for turn in self._turns:
            messages.append({"role": "user", "content": customer_message(turn.customer)})
            if turn.reply is not None:
                messages.append({"role": "assistant", "content": turn.reply})
            else:
                messages.extend(turn.steps)
        return messages

    def dialogue(self, last: int) -> list[str]:
        """The latest exchanges since the last payment, oldest first: "Customer: ..." and
        "Assistant: ..." lines. A bare "네" only means something next to the question it answers.
        """
        turns = self._turns
        for i, turn in enumerate(turns):
            if turn is self._paid_in:  # identity: equal-looking turns are different turns
                turns = turns[i + 1 :]
                break
        lines = []
        for turn in turns[-last:]:
            lines.append(f"Customer: {turn.customer}")
            if turn.reply is not None:
                lines.append(f"Assistant: {json.loads(turn.reply).get('message', '')}")
        return lines

    def _current(self) -> _Turn:
        if not self._turns:
            self._turns.append(_Turn(""))
        return self._turns[-1]
