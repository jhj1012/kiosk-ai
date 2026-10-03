"""WAV encoding with the standard library (no numpy)."""

from __future__ import annotations

import io
import wave


def to_wav(pcm: bytes, sample_rate: int) -> bytes:
    """16-bit mono PCM as a WAV file."""
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(pcm)
    return buffer.getvalue()


def read_wav(data: bytes) -> tuple[bytes, int]:
    """(16-bit mono PCM, sample rate) from a WAV file written by `to_wav`."""
    with wave.open(io.BytesIO(data), "rb") as w:
        if w.getnchannels() != 1 or w.getsampwidth() != 2:
            raise ValueError("expected a 16-bit mono WAV file")
        return w.readframes(w.getnframes()), w.getframerate()
