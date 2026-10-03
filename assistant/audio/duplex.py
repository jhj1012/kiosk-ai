"""Half-duplex: the assistant must not hear itself.

The speech output (TTS phase) wraps playback in `gate.speaking()`. While it is set, and for
`tail_s` afterwards (room echo, the end of the speaker's buffer), the microphone drops its
audio. Today `say()` returns before `listen()` is called again in the same thread, so the gate
only matters once speech output plays in the background.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager


class SpeakingGate:
    def __init__(self, tail_s: float = 0.3, clock: Callable[[], float] = time.monotonic) -> None:
        self.tail_s = tail_s
        self._clock = clock
        self._lock = threading.Lock()
        self._speakers = 0
        self._quiet_from = 0.0

    @contextmanager
    def speaking(self) -> Iterator[None]:
        """Mute the microphone while the body runs (thread-safe, may be nested)."""
        with self._lock:
            self._speakers += 1
        try:
            yield
        finally:
            with self._lock:
                self._speakers -= 1
                self._quiet_from = self._clock() + self.tail_s

    def muted(self) -> bool:
        with self._lock:
            return self._speakers > 0 or self._clock() < self._quiet_from
