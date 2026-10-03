"""The microphone, through `sounddevice` (PortAudio). The only module that imports it.

Frames arrive in PortAudio's thread and wait in a queue until the recorder reads them.
`RawInputStream` gives plain bytes, so numpy is not needed.
"""

from __future__ import annotations

import contextlib
import logging
import queue
import time
from collections.abc import Iterable, Mapping
from typing import Any

from assistant.audio.base import MicError
from assistant.audio.duplex import SpeakingGate
from assistant.config import AudioConfig

log = logging.getLogger(__name__)

MAX_QUEUED_S = 20.0  # older audio is dropped if nobody reads it (the assistant is busy)


def input_devices(devices: Iterable[Mapping[str, Any]]) -> list[tuple[int, str]]:
    """(index, name) of the devices that can record."""
    return [
        (i, str(d.get("name", "")))
        for i, d in enumerate(devices)
        if int(d.get("max_input_channels", 0)) > 0
    ]


def find_device(devices: Iterable[Mapping[str, Any]], wanted: int | str | None) -> int | None:
    """The device index for the `audio.device` setting: None (default), an index or a name part."""
    if wanted is None or wanted == "":
        return None
    inputs = input_devices(devices)
    if isinstance(wanted, int):
        if any(i == wanted for i, _ in inputs):
            return wanted
        raise MicError(f"audio.device {wanted} is not an input device")
    for i, name in inputs:
        if wanted.lower() in name.lower():
            return i
    raise MicError(f"no input device whose name contains {wanted!r}")


class Microphone:
    def __init__(self, config: AudioConfig, gate: SpeakingGate | None = None) -> None:
        self.config = config
        self.gate = gate
        self.sample_rate = config.sample_rate  # the device's rate if it refuses this one
        max_frames = int(MAX_QUEUED_S * 1000 / config.frame_ms)
        self._queue: queue.Queue[bytes] = queue.Queue(maxsize=max_frames)
        self._stream: Any = None
        self.device_name = ""

    def open(self) -> None:
        if self._stream is not None:
            return
        try:
            import sounddevice as sd
        except (ImportError, OSError) as e:
            raise MicError(f"sounddevice (PortAudio) is not available: {e}") from e
        try:
            devices = sd.query_devices()
            device = find_device(devices, self.config.device)
            index = device if device is not None else sd.default.device[0]
            if index is None or index < 0:
                raise MicError("no microphone found (Windows has no default input device)")
            self.device_name = str(devices[index]["name"])
            native = int(devices[index].get("default_samplerate") or 0)
            try:
                stream = self._start(sd, device, self.config.sample_rate)
            except Exception as e:
                # Some drivers (WDM-KS) do not resample: use the device's own rate. The voice
                # detection and Gemini work with any rate.
                if not native or native == self.config.sample_rate:
                    raise
                log.info("%d Hz refused (%s); using %d Hz", self.config.sample_rate, e, native)
                stream = self._start(sd, device, native)
        except MicError:
            raise
        except Exception as e:  # sounddevice.PortAudioError, invalid device or sample rate
            raise MicError(f"could not open the microphone: {e}") from e
        self._stream = stream
        log.info("microphone opened: %s, %d Hz", self.device_name, self.sample_rate)

    def _start(self, sd: Any, device: int | None, sample_rate: int) -> Any:
        stream = sd.RawInputStream(
            samplerate=sample_rate,
            blocksize=sample_rate * self.config.frame_ms // 1000,
            channels=1,
            dtype="int16",
            device=device,
            callback=self._on_audio,
        )
        stream.start()
        self.sample_rate = sample_rate
        return stream

    def close(self) -> None:
        stream, self._stream = self._stream, None
        if stream is not None:
            try:
                stream.stop()
                stream.close()
            except Exception as e:
                log.warning("closing the microphone failed: %s", e)
        self.flush()

    def flush(self) -> None:
        while True:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                return

    def read(self, timeout_s: float) -> bytes | None:
        """The next frame. While the assistant speaks no audio arrives; that is not a timeout."""
        deadline = time.monotonic() + timeout_s
        while True:
            try:
                return self._queue.get(timeout=0.1)
            except queue.Empty:
                if self.gate is not None and self.gate.muted():
                    deadline = time.monotonic() + timeout_s
                elif time.monotonic() >= deadline:
                    return None

    def _on_audio(self, data: Any, frames: int, time_info: Any, status: Any) -> None:
        """PortAudio's thread: queue the frame unless the assistant is speaking."""
        if status:
            log.debug("audio status: %s", status)
        if self.gate is not None and self.gate.muted():
            return
        frame = bytes(data)
        try:
            self._queue.put_nowait(frame)
        except queue.Full:
            with contextlib.suppress(queue.Empty):
                self._queue.get_nowait()  # drop the oldest frame
            self._queue.put_nowait(frame)
