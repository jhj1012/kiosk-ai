"""Synthetic audio for tests: 16-bit mono frames of "speech" (a loud tone) and quiet noise."""

from __future__ import annotations

import math
import random
import struct

from assistant.audio.base import MicError
from assistant.config import AudioConfig

RATE = 16000
FRAME_MS = 30
FRAME_SAMPLES = RATE * FRAME_MS // 1000

CONFIG = AudioConfig(
    sample_rate=RATE,
    frame_ms=FRAME_MS,
    calibration_s=0.3,
    threshold_factor=3.0,
    min_threshold=300,
    start_ms=150,
    pre_roll_ms=300,
    silence_end_ms=800,
    min_utterance_ms=300,
    max_utterance_s=15,
)

_random = random.Random(7)


def _pack(samples: list[float]) -> bytes:
    return struct.pack(f"<{len(samples)}h", *(max(-32768, min(32767, int(s))) for s in samples))


def _frames(ms: int) -> int:
    return ms // FRAME_MS


def quiet(ms: int, level: float = 50) -> list[bytes]:
    """Background noise with an RMS of about `level`."""
    return [
        _pack([_random.gauss(0, level) for _ in range(FRAME_SAMPLES)]) for _ in range(_frames(ms))
    ]


def speech(ms: int, amplitude: float = 5000) -> list[bytes]:
    """A loud 220 Hz tone (RMS about amplitude / 1.41)."""
    frames = []
    for f in range(_frames(ms)):
        start = f * FRAME_SAMPLES
        frames.append(
            _pack(
                [
                    amplitude * math.sin(2 * math.pi * 220 * (start + i) / RATE)
                    for i in range(FRAME_SAMPLES)
                ]
            )
        )
    return frames


def zeros(ms: int) -> list[bytes]:
    return [bytes(FRAME_SAMPLES * 2) for _ in range(_frames(ms))]


class FakeSource:
    """Plays a list of frames; then None (no audio), or raises `error` when it is set."""

    def __init__(self, frames: list[bytes] | None = None) -> None:
        self.frames = list(frames or [])
        self.opened = 0
        self.closed = 0
        self.flushed = 0
        self.open_error: MicError | None = None

    def add(self, *chunks: list[bytes]) -> None:
        for chunk in chunks:
            self.frames.extend(chunk)

    def open(self) -> None:
        if self.open_error is not None:
            raise self.open_error
        self.opened += 1

    def close(self) -> None:
        self.closed += 1

    def flush(self) -> None:
        self.flushed += 1

    def read(self, timeout_s: float) -> bytes | None:
        return self.frames.pop(0) if self.frames else None
