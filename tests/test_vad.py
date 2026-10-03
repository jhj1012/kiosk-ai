"""Voice activity detection and recording on synthetic audio (no microphone, no numpy)."""

from __future__ import annotations

import math
import struct
from dataclasses import replace

import pytest

from assistant.audio.base import MicError
from assistant.audio.duplex import SpeakingGate
from assistant.audio.mic import find_device, input_devices
from assistant.audio.recorder import UtteranceRecorder
from assistant.audio.vad import SilentMicError, calibrate, rms
from assistant.audio.wav import read_wav, to_wav
from tests.audio_fakes import CONFIG, FRAME_MS, RATE, FakeSource, quiet, speech, zeros


def started(*chunks: list[bytes], config=CONFIG) -> tuple[UtteranceRecorder, FakeSource]:
    """A recorder calibrated on quiet noise, with `chunks` queued after calibration."""
    source = FakeSource(quiet(int(config.calibration_s * 1000)))
    recorder = UtteranceRecorder(source, config)
    recorder.start()
    source.add(*chunks)
    return recorder, source


def test_rms_of_a_sine_and_of_silence() -> None:
    amplitude = 10000
    samples = [int(amplitude * math.sin(2 * math.pi * i / 100)) for i in range(1000)]
    frame = struct.pack(f"<{len(samples)}h", *samples)
    assert rms(frame) == pytest.approx(amplitude / math.sqrt(2), rel=0.01)
    assert rms(zeros(30)[0]) == 0
    assert rms(b"") == 0


def test_calibration_measures_noise_and_detects_a_blocked_mic() -> None:
    assert 30 < calibrate(quiet(300, level=50)) < 70
    with pytest.raises(SilentMicError):
        calibrate(zeros(300))


def test_silence_only_returns_nothing() -> None:
    recorder, _ = started(quiet(3000))
    assert recorder.record(max_wait_s=2.0) is None


def test_speech_is_one_utterance_with_pre_roll_and_short_tail() -> None:
    recorder, source = started(quiet(600), speech(1200), quiet(1500))
    utterance = recorder.record()
    assert utterance is not None
    assert utterance.ended_by == "silence"
    assert utterance.speech_ms == 1200
    # 300 ms pre-roll + 1200 ms speech + 300 ms tail
    assert utterance.duration_s == pytest.approx(1.8, abs=0.07)
    assert source.flushed == 1  # audio from before listen() is dropped


def test_first_syllable_is_kept() -> None:
    """The frames that triggered the start are in the utterance, not lost."""
    recorder, _ = started(quiet(300), speech(600), quiet(1500))
    utterance = recorder.record()
    assert utterance is not None
    loud = [rms(utterance.pcm[i : i + 960]) > 1000 for i in range(0, len(utterance.pcm), 960)]
    assert sum(loud) == 600 // FRAME_MS


def test_short_pause_does_not_split_the_utterance() -> None:
    recorder, _ = started(quiet(300), speech(600), quiet(450), speech(600), quiet(1500))
    utterance = recorder.record()
    assert utterance is not None
    assert utterance.speech_ms == 1200


def test_long_pause_splits_into_two_utterances() -> None:
    recorder, source = started(quiet(300), speech(600), quiet(1200), speech(900), quiet(1500))
    source.flush = lambda: None  # type: ignore[method-assign]  # keep the queued second part
    first = recorder.record()
    second = recorder.record()
    assert first is not None and second is not None
    assert (first.speech_ms, second.speech_ms) == (600, 900)


def test_too_short_sounds_are_dropped() -> None:
    recorder, _ = started(quiet(300), speech(90), quiet(1500))  # starts, but too short
    assert recorder.record(max_wait_s=1.5) is None


def test_click_shorter_than_start_does_not_start() -> None:
    recorder, _ = started(quiet(300), speech(60), quiet(1000))
    assert recorder.record(max_wait_s=1.0) is None


def test_short_yes_is_kept() -> None:
    """A quick "네" has only ~150 ms of loud audio."""
    recorder, _ = started(quiet(300), speech(150), quiet(1500))
    utterance = recorder.record(max_wait_s=2.0)
    assert utterance is not None
    assert utterance.speech_ms == 150


def test_syllables_with_short_dips_start_an_utterance() -> None:
    """Loud audio does not have to be in a row: "라지 사이즈로" has dips between syllables."""
    syllables = speech(60) + quiet(60) + speech(60) + quiet(30) + speech(60) + quiet(60)
    recorder, _ = started(quiet(300), syllables, quiet(1500))
    utterance = recorder.record(max_wait_s=2.0)
    assert utterance is not None
    assert utterance.speech_ms >= 150


def test_long_speech_is_cut_at_the_maximum() -> None:
    config = replace(CONFIG, max_utterance_s=3.0)
    recorder, _ = started(quiet(300), speech(6000), quiet(1500), config=config)
    utterance = recorder.record()
    assert utterance is not None
    assert utterance.ended_by == "max_length"
    assert utterance.duration_s == pytest.approx(3.0, abs=0.05)


def test_threshold_follows_the_background_noise() -> None:
    recorder, _ = started()
    assert recorder.threshold == CONFIG.min_threshold  # quiet room: the minimum applies
    loud_room = FakeSource(quiet(300, level=400))
    recorder = UtteranceRecorder(loud_room, CONFIG)
    recorder.start()
    assert recorder.threshold == pytest.approx(1200, rel=0.15)
    # Speech that is not clearly louder than the noise does not start an utterance.
    loud_room.add(speech(600, amplitude=800), quiet(1000, level=400))
    assert recorder.record(max_wait_s=1.5) is None


def test_no_audio_is_a_mic_error_and_closes_on_failed_start() -> None:
    recorder, _ = started()
    with pytest.raises(MicError, match="no audio"):
        recorder.record()
    blocked = FakeSource(zeros(300))
    with pytest.raises(SilentMicError):
        UtteranceRecorder(blocked, CONFIG).start()
    assert blocked.closed == 1


def test_wav_round_trip() -> None:
    pcm = b"".join(speech(300))
    data = to_wav(pcm, RATE)
    assert data[:4] == b"RIFF" and data[8:12] == b"WAVE"
    assert read_wav(data) == (pcm, RATE)


def test_speaking_gate_mutes_while_speaking_and_for_the_tail() -> None:
    now = [100.0]
    gate = SpeakingGate(tail_s=0.3, clock=lambda: now[0])
    assert not gate.muted()
    with gate.speaking():
        assert gate.muted()
    assert gate.muted()  # echo tail
    now[0] += 0.31
    assert not gate.muted()


def test_find_device_by_index_or_name() -> None:
    devices = [
        {"name": "Speakers", "max_input_channels": 0},
        {"name": "Microphone Array (Realtek)", "max_input_channels": 2},
        {"name": "USB Mic", "max_input_channels": 1},
    ]
    assert input_devices(devices) == [(1, "Microphone Array (Realtek)"), (2, "USB Mic")]
    assert find_device(devices, None) is None
    assert find_device(devices, 2) == 2
    assert find_device(devices, "usb") == 2
    with pytest.raises(MicError):
        find_device(devices, 0)  # an output device
    with pytest.raises(MicError):
        find_device(devices, "headset")
