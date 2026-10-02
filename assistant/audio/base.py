"""The interface between the recorder and a source of audio frames (the microphone or a fake)."""

from __future__ import annotations

from typing import Protocol


class MicError(Exception):
    """The microphone cannot be opened or stopped delivering audio."""


class FrameSource(Protocol):
    def open(self) -> None:
        """Start capturing. Raises MicError if the device cannot be opened."""
        ...

    def close(self) -> None: ...

    def flush(self) -> None:
        """Drop the audio captured so far (e.g. while the assistant was thinking)."""
        ...

    def read(self, timeout_s: float) -> bytes | None:
        """The next frame of 16-bit mono PCM, or None if none arrived within `timeout_s`."""
        ...
