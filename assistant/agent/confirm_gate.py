"""Code-level safety net for irreversible buttons.

Two kinds of buttons, each matched by a regex from `configs/settings.yaml` (per kiosk):

- payment (`agent.payment_button_pattern`): finishes the payment. Allowed when the customer
  has asked to pay (checked by a small classification request over their latest messages,
  so "결제할게요" counts and nobody is asked "결제하시겠어요?" again), and the same answer
  carries a short read-back of the order and total, which is shown to the customer.
- discard (`agent.discard_button_pattern`): throws the whole order away (e.g. back to start).
  Allowed only right after the customer said yes to the assistant's "confirm" question.
"""

from __future__ import annotations

import re
from collections.abc import Callable

from assistant.screen.model import Element

PAYMENT_NOT_ASKED = (
    "BLOCKED: {label} finishes the payment, but the customer has not asked to pay (or changed "
    "the order since). Do not pay. Ask what they want next."
)
PAYMENT_NO_READ_BACK = (
    'BLOCKED: to press {label}, put a short read-back in "message" in the same answer: the '
    "items with options and quantities and the total shown on the screen, as a statement, "
    "not a question."
)
DISCARD_ASK_FIRST = (
    "BLOCKED: {label} throws away the whole order. Never use it to go back. To leave an "
    "options page without adding the item, use its cancel or back button. Only if the "
    'customer wants to cancel everything, ask them to confirm first ("kind": "confirm").'
)
DISCARD_NOT_AGREED = (
    "BLOCKED: {label} throws away the whole order, and the customer did not clearly agree. "
    "Do not press it."
)

Check = Callable[[], bool]


class ConfirmationGate:
    def __init__(
        self, *, payment_pattern: str = "", discard_pattern: str = "", guard_payment: bool = True
    ) -> None:
        self._payment = (
            re.compile(payment_pattern, re.IGNORECASE)
            if guard_payment and payment_pattern
            else None
        )
        self._discard = re.compile(discard_pattern, re.IGNORECASE) if discard_pattern else None
        self._payment_check: Check | None = None
        self._confirm_check: Check | None = None
        self._answers: dict[str, bool] = {}
        self._read_back = ""
        self.paid_with_read_back = ""  # set when a payment button was let through

    def needs_confirmation(self, element: Element) -> bool:
        return self._kind(element) is not None

    def discards_order(self, element: Element) -> bool:
        """True for buttons that throw the whole order away (e.g. back to the start)."""
        return self._kind(element) == "discard"

    def start_turn(self, *, payment_check: Check | None, confirm_check: Check | None) -> None:
        """Begin a customer turn.

        `payment_check` says whether the customer has asked to pay; `confirm_check` (only after
        a "confirm" reply) whether they said yes to it. Each is called at most once per turn,
        and only if a guarded button is pressed.
        """
        self._payment_check = payment_check
        self._confirm_check = confirm_check
        self._answers = {}
        self.paid_with_read_back = ""

    def start_batch(self, read_back: str) -> None:
        """The read-back message that came with the actions about to run."""
        self._read_back = read_back.strip()

    def blocked_reason(self, element: Element) -> str | None:
        """None if pressing `element` is allowed, else a message for the model."""
        kind = self._kind(element)
        label = element.label
        if kind == "payment":
            if not self._ask("payment", self._payment_check):
                return PAYMENT_NOT_ASKED.format(label=label)
            if not self._read_back:
                return PAYMENT_NO_READ_BACK.format(label=label)
            self.paid_with_read_back = self._read_back
            return None
        if kind == "discard":
            if self._confirm_check is None:
                return DISCARD_ASK_FIRST.format(label=label)
            if not self._ask("discard", self._confirm_check):
                return DISCARD_NOT_AGREED.format(label=label)
        return None

    def _ask(self, key: str, check: Check | None) -> bool:
        if check is None:
            return False
        if key not in self._answers:
            self._answers[key] = check()
        return self._answers[key]

    def _kind(self, element: Element) -> str | None:
        name = element.name.strip()
        if self._payment is not None and self._payment.search(name):
            return "payment"
        if self._discard is not None and self._discard.search(name):
            return "discard"
        return None
