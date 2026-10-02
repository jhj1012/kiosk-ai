"""Decide when the next customer starts, so the assistant can run all day.

A kiosk keeps running after a customer leaves. A new customer gets a fresh conversation: the
previous customer's history, remembered answers and payment approval must not carry over, and
are not sent to the model again.

Nothing kiosk-specific is hardcoded. The idle screen (the kiosk's "waiting for a customer"
screen) is learned when the assistant starts. A customer has left when:

- the kiosk is back on its idle screen and nobody talked for `new_customer_after_s`
  (a customer who asks "이제 어디로 가요?" right after paying is still the same customer), or
- nobody talked for `abandoned_after_s`, whatever the screen shows (someone walked away in the
  middle of an order; the next person must not silently inherit their cart).
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from enum import StrEnum

from assistant.screen.model import Snapshot

log = logging.getLogger(__name__)


class Switch(StrEnum):
    SAME = "same"  # the same customer continues
    AFTER_IDLE = "after_idle"  # previous order finished; kiosk waiting on its idle screen
    ABANDONED = "abandoned"  # long silence; the screen may still show someone else's order


class CustomerTracker:
    def __init__(
        self,
        *,
        new_customer_after_s: float,
        abandoned_after_s: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.new_customer_after_s = new_customer_after_s
        self.abandoned_after_s = abandoned_after_s
        self._clock = clock
        self.idle_controls: frozenset[str] | None = None
        self._last_activity: float | None = None

    def learn_idle_screen(self, snapshot: Snapshot) -> None:
        """Remember `snapshot` as the kiosk's idle (start) screen."""
        self.idle_controls = snapshot.control_names()
        log.info("idle screen learned: %s", ", ".join(sorted(self.idle_controls)) or "(none)")

    def is_idle(self, snapshot: Snapshot) -> bool:
        return self.idle_controls is not None and snapshot.control_names() == self.idle_controls

    def check(self, snapshot: Snapshot) -> Switch:
        """Before a customer message: is this still the same customer?"""
        if self._last_activity is None:
            return Switch.SAME  # nobody talked yet: the conversation is empty anyway
        quiet = self._clock() - self._last_activity
        if quiet >= self.abandoned_after_s:
            return Switch.AFTER_IDLE if self.is_idle(snapshot) else Switch.ABANDONED
        if quiet >= self.new_customer_after_s and self.is_idle(snapshot):
            return Switch.AFTER_IDLE
        return Switch.SAME

    def touch(self) -> None:
        """Record customer activity (call when a turn ends)."""
        self._last_activity = self._clock()

    def forget(self) -> None:
        """A new conversation started: no activity yet."""
        self._last_activity = None
