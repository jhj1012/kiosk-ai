"""Wait until the screen stops changing after an action."""

from __future__ import annotations

import time
from collections.abc import Callable

from assistant.screen.model import Snapshot


def wait_until_settled(
    read: Callable[[], Snapshot],
    *,
    timeout_s: float,
    interval_s: float,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> Snapshot:
    """Re-read the screen until two reads in a row match and it is not busy.

    "Busy" means no control is enabled, e.g. while a kiosk processes a payment; the wait
    continues then, until the next screen appears. Returns the last read on timeout.
    """
    deadline = clock() + timeout_s
    previous = read()
    while True:
        sleep(interval_s)
        current = read()
        if current.signature() == previous.signature() and not current.busy:
            return current
        if clock() >= deadline:
            return current
        previous = current
