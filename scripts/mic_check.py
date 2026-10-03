"""Check the microphone and speech recognition (developer helper).

    uv run python scripts/mic_check.py --list          # input devices (for audio.device)
    uv run python scripts/mic_check.py --levels 10     # live levels for 10 s (tune thresholds)
    uv run python scripts/mic_check.py                 # record one utterance, transcribe it
    uv run python scripts/mic_check.py --file a.wav    # transcribe a WAV file instead

Settings come from configs/ (audio: and stt:, with *.local.yaml overrides). Recording one
utterance prints the text and the latency: how long the speech recognition took after the
end of speech was detected (that detection itself takes audio.silence_end_ms).
"""

from __future__ import annotations

import argparse
import sys
import time
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from assistant.audio.base import MicError  # noqa: E402
from assistant.audio.mic import Microphone, input_devices  # noqa: E402
from assistant.audio.recorder import UtteranceRecorder  # noqa: E402
from assistant.audio.vad import SilentMicError, rms  # noqa: E402
from assistant.config import AudioConfig, Config, load_config, load_env_file  # noqa: E402
from assistant.llm.client import GeminiChatModel, LlmError  # noqa: E402
from assistant.stt.transcriber import GeminiTranscriber  # noqa: E402

BAR_WIDTH = 50
BAR_FULL_SCALE = 3000.0  # RMS shown as a full bar


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--list", action="store_true", help="list input devices")
    parser.add_argument("--levels", type=float, metavar="SECONDS", help="show live levels")
    parser.add_argument("--file", type=Path, help="transcribe this WAV file")
    parser.add_argument("--device", help="input device index or name part (audio.device)")
    parser.add_argument("--model", help="speech recognition model (stt.model)")
    parser.add_argument("--hints", help="comma-separated vocabulary hints, e.g. 할메가커피")
    parser.add_argument("--save", type=Path, help="also save the recording to this WAV file")
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]

    config = load_config()
    audio = config.audio
    if args.device is not None:
        audio = replace(audio, device=int(args.device) if args.device.isdigit() else args.device)
    if args.list:
        return list_devices()

    try:
        if args.levels:
            return show_levels(Microphone(audio), audio, args.levels)
        if args.file:
            wav = args.file.read_bytes()
        else:
            wav = record(UtteranceRecorder(Microphone(audio), audio))
            if wav is None:
                return 1
            if args.save:
                args.save.write_bytes(wav)
                print(f"saved {args.save}")
    except MicError as e:
        print(f"Microphone error: {e}", file=sys.stderr)
        if isinstance(e, SilentMicError):
            print(
                "Windows Settings > Privacy & security > Microphone: turn on microphone access "
                "and 'Let desktop apps access your microphone'.",
                file=sys.stderr,
            )
        return 1
    return transcribe(wav, config, args.model, args.hints)


def list_devices() -> int:
    import sounddevice as sd

    devices = sd.query_devices()
    default = sd.default.device[0]
    for index, name in input_devices(devices):
        api = sd.query_hostapis(devices[index]["hostapi"])["name"]
        mark = "*" if index == default else " "
        print(f"{mark} {index:3}  {name}  [{api}]")
    print("* = Windows default. Set audio.device in configs/settings.local.yaml to change it.")
    return 0


def show_levels(mic: Microphone, audio: AudioConfig, seconds: float) -> int:
    recorder = UtteranceRecorder(mic, audio)
    print("Stay quiet for a moment (measuring the background noise)...")
    noise = recorder.start()
    threshold = recorder.threshold
    print(f"{mic.device_name}: noise {noise:.0f}, speech threshold {threshold:.0f}. Talk now.")
    mark = min(BAR_WIDTH - 1, int(threshold / BAR_FULL_SCALE * BAR_WIDTH))
    end = time.monotonic() + seconds
    try:
        while time.monotonic() < end:
            frame = mic.read(2.0)
            if frame is None:
                raise MicError("no audio from the microphone")
            level = rms(frame)
            filled = min(BAR_WIDTH, int(level / BAR_FULL_SCALE * BAR_WIDTH))
            bar = ["#" if i < filled else " " for i in range(BAR_WIDTH)]
            bar[mark] = "|"
            loud = "SPEECH" if level >= threshold else ""
            print(f"\r{level:6.0f} [{''.join(bar)}] {loud:6}", end="", flush=True)
    finally:
        print()
        recorder.stop()
    return 0


def record(recorder: UtteranceRecorder) -> bytes | None:
    print("Stay quiet for a moment (measuring the background noise)...")
    noise = recorder.start()
    print(f"noise {noise:.0f}, threshold {recorder.threshold:.0f}. Say something (max 20 s wait).")
    try:
        utterance = recorder.record(max_wait_s=20)
    finally:
        recorder.stop()
    if utterance is None:
        print("No speech detected.")
        return None
    print(
        f"recorded {utterance.duration_s:.1f} s ({utterance.speech_ms} ms loud, "
        f"ended by {utterance.ended_by})"
    )
    return utterance.wav()


def transcribe(wav: bytes, config: Config, model: str | None, hints: str | None) -> int:
    load_env_file()
    stt = config.stt
    if model:
        stt = replace(stt, model=model)
    try:
        llm = GeminiChatModel(stt.llm_config(config.llm.api_key_env))
        start = time.monotonic()
        words = [h.strip() for h in hints.split(",")] if hints else []
        transcript = GeminiTranscriber(llm).transcribe(wav, words)
    except LlmError as e:
        print(f"Speech recognition error: {e}", file=sys.stderr)
        return 1
    seconds = time.monotonic() - start
    if transcript.heard:
        print(f"text: {transcript.text}")
    else:
        print("no speech (the model heard noise or silence)")
    print(f"speech recognition ({stt.model}): {seconds:.2f} s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
