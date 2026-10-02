"""Record one utterance: frames from a FrameSource, cut by the voice activity detection."""

from __future__ import annotations

import logging
import math
from dataclasses import replace

from assistant.audio.base import FrameSource, MicError
from assistant.audio.vad import Dropped, Segmenter, Utterance, calibrate
from assistant.config import AudioConfig

log = logging.getLogger(__name__)

NO_AUDIO_TIMEOUT_S = 2.0  # a running stream delivers a frame every few ms


class UtteranceRecorder:
    def __init__(self, source: FrameSource, config: AudioConfig) -> None:
        self.source = source
        self.config = config
        self._segmenter: Segmenter | None = None

    @property
    def started(self) -> bool:
        return self._segmenter is not None

    @property
    def noise_level(self) -> float:
        return self._segmenter.noise_level if self._segmenter is not None else 0.0

    @property
    def threshold(self) -> float:
        return self._segmenter.threshold if self._segmenter is not None else 0.0

    def start(self) -> float:
        """Open the source and measure the background noise. Returns the noise level."""
        self.source.open()
        try:
            noise = self._calibrate()
        except Exception:
            self.source.close()
            raise
        config = replace(self.config, sample_rate=self.source.sample_rate)
        self._segmenter = Segmenter(config, noise)
        log.info("microphone ready: noise level %.0f, threshold %.0f", noise, self.threshold)
        return noise

    def stop(self) -> None:
        self._segmenter = None
        self.source.close()

    def recalibrate(self) -> float:
        """Measure the background noise again (e.g. after a long utterance of only noise)."""
        if self._segmenter is None:
            return self.start()
        self.source.flush()
        self._segmenter.noise_level = self._calibrate()
        self._segmenter.reset()
        log.info("recalibrated: noise level %.0f, threshold %.0f", self.noise_level, self.threshold)
        return self._segmenter.noise_level

    def record(self, max_wait_s: float | None = None) -> Utterance | None:
        """Wait for someone to speak and return the utterance.

        Audio captured before this call is dropped (the assistant was thinking or speaking).
        Returns None if nobody started speaking within `max_wait_s` seconds of audio.
        """
        if self._segmenter is None:
            self.start()
        segmenter = self._segmenter
        assert segmenter is not None
        self.source.flush()
        segmenter.reset()
        waited_ms = 0
        while True:
            result = segmenter.feed(self._read())
            if isinstance(result, Utterance):
                log.info(
                    "utterance: %.1f s, %d ms loud, ended by %s",
                    result.duration_s,
                    result.speech_ms,
                    result.ended_by,
                )
                return result
            if isinstance(result, Dropped):
                log.debug("dropped a short sound (%d ms loud)", result.speech_ms)
            waited_ms += self.config.frame_ms
            timed_out = max_wait_s is not None and waited_ms >= max_wait_s * 1000
            if timed_out and not segmenter.speaking:  # an utterance in progress is finished
                return None

    def _calibrate(self) -> float:
        count = max(1, math.ceil(self.config.calibration_s * 1000 / self.config.frame_ms))
        return calibrate([self._read() for _ in range(count)])

    def _read(self) -> bytes:
        frame = self.source.read(NO_AUDIO_TIMEOUT_S)
        if frame is None:
            raise MicError(
                f"no audio from the microphone for {NO_AUDIO_TIMEOUT_S:.0f} s "
                "(was it unplugged or taken by another program?)"
            )
        return frame
