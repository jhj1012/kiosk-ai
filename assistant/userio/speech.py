"""Speech input: the customer speaks, the agent gets the recognized text.

`SpeechInput.listen()` waits for an utterance (voice activity detection), sends it to the
speech recognizer and returns the text, exactly like a typed line. Noise and non-speech are
skipped. Microphone and API errors are reported and listening goes on: the assistant runs all
day and must never stop because of them.

It runs in the agent's worker thread (run_session calls listen()), so the vocabulary hints
callable may read the kiosk screen.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Sequence
from datetime import datetime
from pathlib import Path
from typing import Protocol

from assistant.audio.base import MicError
from assistant.audio.vad import SilentMicError, Utterance
from assistant.llm.client import LlmError
from assistant.stt.transcriber import Transcript
from assistant.userio.base import AssistantState, UserOutput

log = logging.getLogger(__name__)

USER_PREFIX = "나(음성)> "
NOT_HEARD_MESSAGE = "죄송해요, 잘 못 들었어요. 다시 한 번 말씀해 주시겠어요?"
MIC_RETRY_S = 5.0  # how often to try the microphone again after an error
PUSH_TO_TALK_WAIT_S = 10.0  # after Enter, wait this long for speech
NO_SPEECH_RECALIBRATE = 2  # long noise-only utterances in a row before measuring noise again


class Recorder(Protocol):
    def start(self) -> float: ...

    def stop(self) -> None: ...

    def recalibrate(self) -> float: ...

    def record(self, max_wait_s: float | None = None) -> Utterance | None: ...


class Transcriber(Protocol):
    def transcribe(self, wav: bytes, hints: Sequence[str] = ()) -> Transcript: ...


class SpeechInput:
    def __init__(
        self,
        recorder: Recorder,
        transcriber: Transcriber,
        output: UserOutput,
        *,
        hints: Callable[[], Sequence[str]] | None = None,
        push_to_talk: Callable[[], bool] | None = None,
        save_dir: Path | None = None,
        notify: Callable[[str], None] = print,
        sleep: Callable[[float], None] = time.sleep,
        verbose: bool = False,
    ) -> None:
        """`push_to_talk` (developer mode) blocks until the user wants to speak and returns
        False when input ended. `notify` shows status messages to the operator (console)."""
        self.recorder = recorder
        self.transcriber = transcriber
        self.output = output
        self.hints = hints
        self.push_to_talk = push_to_talk
        self.save_dir = save_dir
        self.notify = notify
        self.sleep = sleep
        self.verbose = verbose
        self._ready = False
        self._mic_problem = ""  # last microphone error shown, so it is not repeated every 5 s
        self._noise_only = 0

    def listen(self) -> str | None:
        while True:
            if not self._ensure_ready():
                self.sleep(MIC_RETRY_S)
                continue
            if self.push_to_talk is not None:
                self.notify("    (Enter를 누르고 말씀하세요)")
                if not self.push_to_talk():
                    return None
            try:
                utterance = self.recorder.record(
                    PUSH_TO_TALK_WAIT_S if self.push_to_talk is not None else None
                )
            except MicError as e:
                self._mic_failed(e)
                continue
            if utterance is None:
                continue
            text = self._transcribe(utterance)
            if text:
                return text
            self.output.set_state(AssistantState.LISTENING)

    def close(self) -> None:
        if self._ready:
            self.recorder.stop()
            self._ready = False

    def _ensure_ready(self) -> bool:
        if self._ready:
            return True
        try:
            self.recorder.start()
        except MicError as e:
            self._mic_failed(e)
            return False
        self._ready = True
        if self._mic_problem:
            self.notify("마이크가 다시 연결되었어요.")
        self._mic_problem = ""
        self.notify("    (말씀하시면 듣고 있어요)")
        return True

    def _mic_failed(self, error: MicError) -> None:
        if self._ready:
            self.recorder.stop()
            self._ready = False
        problem = str(error)
        log.error("microphone: %s", problem)
        if problem == self._mic_problem:
            return
        self._mic_problem = problem
        self.notify(f"마이크 오류: {problem}")
        if isinstance(error, SilentMicError):
            self.notify(
                "마이크 소리가 전혀 들어오지 않아요. Windows 설정 → 개인 정보 및 보안 → 마이크에서 "
                "'마이크 액세스'와 '데스크톱 앱에서 마이크에 액세스하도록 허용'을 켜 주세요."
            )
        else:
            self.notify("마이크가 연결되어 있는지 확인해 주세요. 5초마다 다시 시도해요.")

    def _transcribe(self, utterance: Utterance) -> str:
        """The recognized words, or "" for noise, non-speech and errors."""
        self.output.set_state(AssistantState.THINKING)
        wav = utterance.wav()
        if self.save_dir is not None:
            self._save(wav)
        hints = self._hints()
        start = time.monotonic()
        try:
            transcript = self.transcriber.transcribe(wav, hints)
        except LlmError as e:
            log.error("speech recognition failed: %s", e)
            self.notify(f"    (음성 인식 오류: {e})")
            self.output.say(NOT_HEARD_MESSAGE)
            return ""
        seconds = time.monotonic() - start
        if not transcript.heard:
            log.info("not speech (%.1f s audio, stt %.1f s)", utterance.duration_s, seconds)
            if self.verbose:
                self.notify(f"    (말소리가 아니에요: {utterance.duration_s:.1f}초, 무시)")
            self._after_noise(utterance)
            return ""
        self._noise_only = 0
        log.info(
            "heard (%.1f s audio, stt %.1f s): %s", utterance.duration_s, seconds, transcript.text
        )
        self.notify(f"{USER_PREFIX}{transcript.text}")
        return transcript.text

    def _after_noise(self, utterance: Utterance) -> None:
        """Steady loud noise (a coffee grinder) keeps the detector busy: measure it again."""
        if utterance.ended_by != "max_length":
            return
        self._noise_only += 1
        if self._noise_only >= NO_SPEECH_RECALIBRATE:
            self._noise_only = 0
            try:
                self.recorder.recalibrate()
            except MicError as e:
                self._mic_failed(e)

    def _hints(self) -> Sequence[str]:
        if self.hints is None:
            return ()
        try:
            return self.hints()
        except Exception as e:  # the kiosk window may be gone; hints are optional
            log.debug("no vocabulary hints: %s", e)
            return ()

    def _save(self, wav: bytes) -> None:
        assert self.save_dir is not None
        try:
            self.save_dir.mkdir(parents=True, exist_ok=True)
            path = self.save_dir / f"utterance-{datetime.now():%Y%m%d-%H%M%S-%f}.wav"
            path.write_bytes(wav)
            log.info("saved %s", path)
        except OSError as e:
            log.warning("could not save the recording: %s", e)
