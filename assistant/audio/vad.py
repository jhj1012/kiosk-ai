"""Energy-based voice activity detection on 16-bit mono PCM frames.

Pure Python (no numpy), so it runs in CI. A frame counts as loud when its RMS level is above
max(noise level x `threshold_factor`, `min_threshold`). The noise level is measured at start-up
(`calibrate`) and keeps adapting while nobody speaks.

`Segmenter` turns a stream of frames into utterances: it starts when the last 300 ms contain
`start_ms` of loud audio (not necessarily in a row: syllables have short dips between them),
keeping `pre_roll_ms` from before so the first syllable is not cut. It ends after
`silence_end_ms` of quiet, drops utterances with less than `min_utterance_ms` of loud audio
(coughs, clicks) and cuts them at `max_utterance_s`.
"""

from __future__ import annotations

import math
import statistics
from array import array
from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from assistant.audio.base import MicError
from assistant.audio.wav import to_wav
from assistant.config import AudioConfig

SAMPLE_BYTES = 2  # 16-bit samples
CONTINUE_RATIO = 0.6  # once speaking, quieter sounds (soft word endings) still count as speech
NOISE_ADAPT = 0.05  # how fast the noise level follows the background while nobody speaks
TAIL_MS = 300  # quiet audio kept after the last loud frame
START_WINDOW_MS = 300  # start_ms of loud audio within this window starts an utterance


class SilentMicError(MicError):
    """The microphone delivers only digital zeros (typically: Windows mic access is off)."""


def rms(frame: bytes) -> float:
    """Root mean square level of 16-bit little-endian mono samples (0..32768)."""
    samples = array("h")
    samples.frombytes(frame[: len(frame) - len(frame) % SAMPLE_BYTES])
    if not samples:
        return 0.0
    return math.sqrt(sum(s * s for s in samples) / len(samples))


def calibrate(frames: Sequence[bytes]) -> float:
    """Background noise level from frames recorded while nobody speaks.

    The median ignores a single click. Only zeros means the mic is blocked, not quiet: real
    microphones always pick up some noise.
    """
    if not frames:
        raise ValueError("no frames to calibrate with")
    if not any(any(frame) for frame in frames):
        raise SilentMicError("the microphone delivers only silence (digital zeros)")
    return statistics.median(rms(f) for f in frames)


@dataclass(frozen=True)
class Utterance:
    pcm: bytes  # 16-bit mono
    sample_rate: int
    speech_ms: int  # loud audio in it
    ended_by: Literal["silence", "max_length"]

    @property
    def duration_s(self) -> float:
        return len(self.pcm) / SAMPLE_BYTES / self.sample_rate

    def wav(self) -> bytes:
        return to_wav(self.pcm, self.sample_rate)


@dataclass(frozen=True)
class Dropped:
    """A sound too short to be speech."""

    speech_ms: int


class Segmenter:
    """Feed frames one at a time; `feed` returns an Utterance or Dropped when one ends."""

    def __init__(self, config: AudioConfig, noise_level: float) -> None:
        self.config = config
        self.noise_level = noise_level
        frame_ms = config.frame_ms
        self._start_frames = max(1, math.ceil(config.start_ms / frame_ms))
        self._end_frames = max(1, math.ceil(config.silence_end_ms / frame_ms))
        self._tail_frames = min(self._end_frames, math.ceil(TAIL_MS / frame_ms))
        self._max_frames = max(1, int(config.max_utterance_s * 1000 / frame_ms))
        self._pre_roll_frames = math.ceil(config.pre_roll_ms / frame_ms)
        window = max(self._start_frames, math.ceil(START_WINDOW_MS / frame_ms))
        self._before: deque[bytes] = deque(maxlen=self._pre_roll_frames + window)
        self._recent: deque[bool] = deque(maxlen=window)  # loud or not, while waiting
        self._frames: list[bytes] = []
        self._quiet = 0  # quiet frames in a row while speaking
        self._loud = 0  # loud frames in the current utterance
        self.speaking = False

    @property
    def threshold(self) -> float:
        return max(self.noise_level * self.config.threshold_factor, self.config.min_threshold)

    def reset(self) -> None:
        """Forget any audio heard so far (e.g. after the microphone buffer was flushed)."""
        self._before.clear()
        self._recent.clear()
        self._frames = []
        self._quiet = self._loud = 0
        self.speaking = False

    def feed(self, frame: bytes) -> Utterance | Dropped | None:
        level = rms(frame)
        if not self.speaking:
            return self._wait(frame, level)
        self._frames.append(frame)
        if level >= self.threshold * CONTINUE_RATIO:
            self._quiet = 0
            self._loud += 1
        else:
            self._quiet += 1
        if self._quiet >= self._end_frames:
            return self._finish("silence")
        if len(self._frames) >= self._max_frames:
            return self._finish("max_length")
        return None

    def _wait(self, frame: bytes, level: float) -> None:
        self._before.append(frame)
        loud = level >= self.threshold
        self._recent.append(loud)
        if not loud:
            self.noise_level += (level - self.noise_level) * NOISE_ADAPT
        if sum(self._recent) >= self._start_frames:
            # Keep pre_roll_ms before the first loud frame of the window.
            first_loud = len(self._before) - len(self._recent) + self._recent.index(True)
            keep_from = max(0, first_loud - self._pre_roll_frames)
            self.speaking = True
            self._frames = list(self._before)[keep_from:]
            self._loud = sum(self._recent)
            self._quiet = 0
            self._before.clear()
            self._recent.clear()
        return None

    def _finish(self, ended_by: Literal["silence", "max_length"]) -> Utterance | Dropped:
        frames = self._frames
        if ended_by == "silence":
            frames = frames[: len(frames) - self._quiet + self._tail_frames]
        speech_ms = self._loud * self.config.frame_ms
        self.reset()
        if speech_ms < self.config.min_utterance_ms:
            return Dropped(speech_ms)
        return Utterance(b"".join(frames), self.config.sample_rate, speech_ms, ended_by)
