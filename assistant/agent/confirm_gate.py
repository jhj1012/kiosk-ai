"""Code-level safety net: irreversible buttons need the customer's explicit yes.

Two kinds of buttons, each matched by a regex from `configs/settings.yaml` (per kiosk):

- payment (`agent.payment_button_pattern`): finishes the payment;
- discard (`agent.discard_button_pattern`): throws the whole order away (e.g. back to start).

Pressing one is blocked unless, in this turn, the customer answered the assistant's "confirm"
reply and a small classification request says the answer was a clear yes.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass

from assistant.screen.model import Element


@dataclass(frozen=True)
class _Rule:
    regex: re.Pattern[str]
    ask_first: str
    not_agreed: str


PAYMENT = (
    "BLOCKED: {label} finishes the payment. Do not press it yet. First read back the order "
    '(items, options, quantities) and the total amount, and ask for a clear yes ("kind": '
    '"confirm").',
    "BLOCKED: {label} finishes the payment, but the customer did not clearly agree. Do not "
    "pay. Follow what the customer said, or ask again.",
)
DISCARD = (
    "BLOCKED: {label} throws away the whole order. Never use it to go back. To leave an "
    "options page without adding the item, use its cancel or back button. Only if the "
    'customer wants to cancel everything, ask them to confirm first ("kind": "confirm").',
    "BLOCKED: {label} throws away the whole order, and the customer did not clearly agree. "
    "Do not press it.",
)


class ConfirmationGate:
    def __init__(
        self, *, payment_pattern: str = "", discard_pattern: str = "", confirm_payment: bool = True
    ) -> None:
        self._rules: list[_Rule] = []
        if confirm_payment and payment_pattern:
            self._rules.append(_Rule(re.compile(payment_pattern, re.IGNORECASE), *PAYMENT))
        if discard_pattern:
            self._rules.append(_Rule(re.compile(discard_pattern, re.IGNORECASE), *DISCARD))
        self._check: Callable[[], bool] | None = None
        self._approved: bool | None = None

    def needs_confirmation(self, element: Element) -> bool:
        return self._rule(element) is not None

    def start_turn(self, check: Callable[[], bool] | None) -> None:
        """Begin a customer turn.

        `check` is given when the previous reply asked the customer to confirm; it is called at
        most once, only if a guarded button is pressed, and returns True if the customer agreed.
        """
        self._check = check
        self._approved = None

    def blocked_reason(self, element: Element) -> str | None:
        """None if pressing `element` is allowed, else a message for the model."""
        rule = self._rule(element)
        if rule is None:
            return None
        if self._check is None:
            return rule.ask_first.format(label=element.label)
        if self._approved is None:
            self._approved = self._check()
        return None if self._approved else rule.not_agreed.format(label=element.label)

    def _rule(self, element: Element) -> _Rule | None:
        name = element.name.strip()
        return next((r for r in self._rules if r.regex.search(name)), None)
