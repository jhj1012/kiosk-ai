"""Code-level safety net: no payment without the customer's explicit yes.

Pressing a button whose name matches `agent.payment_button_pattern` is blocked unless, in this
turn, the customer answered the assistant's payment read-back (a "confirm" reply) and a small
classification request says the answer was a clear yes.
"""

from __future__ import annotations

import re
from collections.abc import Callable

from assistant.screen.model import Element

ASK_FIRST = (
    "BLOCKED: {label} finishes the payment. Do not press it yet. First read back the order "
    '(items, options, quantities) and the total amount, and ask for a clear yes ("kind": '
    '"confirm").'
)
NOT_AGREED = (
    "BLOCKED: {label} finishes the payment, but the customer did not clearly agree. Do not "
    "pay. Follow what the customer said, or ask again."
)


class PaymentGate:
    def __init__(self, pattern: str, *, enabled: bool = True) -> None:
        self._regex = re.compile(pattern, re.IGNORECASE) if enabled and pattern else None
        self._check: Callable[[], bool] | None = None
        self._approved: bool | None = None

    def is_payment_button(self, element: Element) -> bool:
        return self._regex is not None and bool(self._regex.search(element.name.strip()))

    def start_turn(self, check: Callable[[], bool] | None) -> None:
        """Begin a customer turn.

        `check` is given when the previous reply asked to confirm the payment; it is called at
        most once, only if a payment button is pressed, and returns True if the customer agreed.
        """
        self._check = check
        self._approved = None

    def blocked_reason(self, element: Element) -> str | None:
        """None if pressing `element` is allowed, else a message for the model."""
        if not self.is_payment_button(element):
            return None
        if self._check is None:
            return ASK_FIRST.format(label=element.label)
        if self._approved is None:
            self._approved = self._check()
        return None if self._approved else NOT_AGREED.format(label=element.label)
