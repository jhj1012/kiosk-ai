"""The speech input loop with a fake recorder and a fake transcriber (no mic, no API)."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from assistant.agent.loop import Agent
from assistant.agent.session import GREETING, run_session
from assistant.audio.base import MicError
from assistant.audio.vad import SilentMicError, Utterance
from assistant.llm.client import LlmError
from assistant.stt.transcriber import Transcript
from assistant.userio.base import AssistantState
from assistant.userio.speech import (
    MIC_RETRY_S,
    NOT_HEARD_MESSAGE,
    PUSH_TO_TALK_WAIT_S,
    USER_PREFIX,
    SpeechInput,
)
from tests.agent_fakes import FAST_SCREEN, FakeLlm, FakeScreen, RecordingOutput, agent_config, reply
from tests.audio_fakes import RATE
from tests.screen_fakes import button, window

Event = Utterance | MicError | None


def utterance(ended_by: str = "silence") -> Utterance:
    return Utterance(bytes(RATE), RATE, 800, ended_by)  # type: ignore[arg-type]


class FakeRecorder:
    def __init__(self, *events: Event, start_errors: Sequence[MicError] = ()) -> None:
        self.events = list(events)
        self.start_errors = list(start_errors)
        self.starts = self.stops = self.recalibrations = 0
        self.waits: list[float | None] = []

    def start(self) -> float:
        if self.start_errors:
            raise self.start_errors.pop(0)
        self.starts += 1
        return 50.0

    def stop(self) -> None:
        self.stops += 1

    def recalibrate(self) -> float:
        self.recalibrations += 1
        return 50.0

    def record(self, max_wait_s: float | None = None) -> Utterance | None:
        self.waits.append(max_wait_s)
        if not self.events:
            raise AssertionError("listened more often than scripted")
        event = self.events.pop(0)
        if isinstance(event, MicError):
            raise event
        return event


class FakeTranscriber:
    def __init__(self, *results: Transcript | Exception) -> None:
        self.results = list(results)
        self.hints: list[Sequence[str]] = []

    def transcribe(self, wav: bytes, hints: Sequence[str] = ()) -> Transcript:
        self.hints.append(hints)
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


def said(text: str) -> Transcript:
    return Transcript(text, True, 1.0)


NOISE = Transcript("", False, 1.0)


def make_input(
    recorder: FakeRecorder, transcriber: FakeTranscriber, **kwargs: object
) -> tuple[SpeechInput, RecordingOutput, list[str], list[float]]:
    output = RecordingOutput()
    notes: list[str] = []
    sleeps: list[float] = []
    speech = SpeechInput(
        recorder, transcriber, output, notify=notes.append, sleep=sleeps.append, **kwargs
    )
    return speech, output, notes, sleeps


def test_recognized_text_is_returned_and_shown() -> None:
    recorder = FakeRecorder(utterance())
    speech, output, notes, _ = make_input(
        recorder, FakeTranscriber(said("아이스 아메리카노 주세요"))
    )
    assert speech.listen() == "아이스 아메리카노 주세요"
    assert f"{USER_PREFIX}아이스 아메리카노 주세요" in notes
    assert recorder.starts == 1
    assert recorder.waits == [None]  # hands-free: wait as long as it takes
    assert ("state", AssistantState.THINKING) in output.events


def test_noise_is_skipped_and_listening_goes_on() -> None:
    recorder = FakeRecorder(utterance(), None, utterance())
    speech, output, notes, _ = make_input(recorder, FakeTranscriber(NOISE, said("네")))
    assert speech.listen() == "네"
    assert output.messages == []  # noise is not answered
    assert not any(n.startswith(USER_PREFIX) for n in notes[:-1])


def test_api_error_says_so_and_keeps_listening() -> None:
    recorder = FakeRecorder(utterance(), utterance())
    speech, output, notes, _ = make_input(recorder, FakeTranscriber(LlmError("429"), said("네")))
    assert speech.listen() == "네"
    assert output.messages == [("say", NOT_HEARD_MESSAGE)]
    assert any("음성 인식 오류" in n for n in notes)


def test_missing_mic_is_retried_and_reported_once() -> None:
    no_mic = MicError("could not open the microphone")
    recorder = FakeRecorder(utterance(), start_errors=[no_mic, MicError(str(no_mic))])
    speech, _, notes, sleeps = make_input(recorder, FakeTranscriber(said("네")))
    assert speech.listen() == "네"
    assert sleeps == [MIC_RETRY_S, MIC_RETRY_S]
    assert sum("마이크 오류" in n for n in notes) == 1
    assert "마이크가 다시 연결되었어요." in notes


def test_blocked_mic_explains_the_windows_privacy_setting() -> None:
    recorder = FakeRecorder(utterance(), start_errors=[SilentMicError("zeros")])
    speech, _, notes, _ = make_input(recorder, FakeTranscriber(said("네")))
    speech.listen()
    assert any("개인 정보 및 보안" in n for n in notes)


def test_mic_lost_while_listening_is_reopened() -> None:
    recorder = FakeRecorder(MicError("no audio"), utterance())
    speech, _, _, _ = make_input(recorder, FakeTranscriber(said("네")))
    assert speech.listen() == "네"
    assert (recorder.starts, recorder.stops) == (2, 1)


def test_push_to_talk_waits_for_enter_and_can_quit() -> None:
    presses = [True, False]
    recorder = FakeRecorder(utterance())
    speech, _, _, _ = make_input(
        recorder, FakeTranscriber(said("네")), push_to_talk=lambda: presses.pop(0)
    )
    assert speech.listen() == "네"
    assert recorder.waits == [PUSH_TO_TALK_WAIT_S]
    assert speech.listen() is None


def test_vocabulary_hints_are_passed_and_failures_ignored() -> None:
    transcriber = FakeTranscriber(said("네"), said("네"))
    hints = [["할메가커피"]]

    def read_hints() -> list[str]:
        if not hints:
            raise RuntimeError("window gone")
        return hints.pop()

    speech, _, _, _ = make_input(
        FakeRecorder(utterance(), utterance()), transcriber, hints=read_hints
    )
    speech.listen()
    speech.listen()
    assert transcriber.hints == [["할메가커피"], ()]


def test_recordings_are_saved_only_when_asked(tmp_path: Path) -> None:
    speech, _, _, _ = make_input(
        FakeRecorder(utterance()), FakeTranscriber(said("네")), save_dir=tmp_path / "rec"
    )
    speech.listen()
    saved = list((tmp_path / "rec").glob("*.wav"))
    assert len(saved) == 1 and saved[0].read_bytes()[:4] == b"RIFF"


def test_long_noise_recalibrates_the_detector() -> None:
    recorder = FakeRecorder(utterance("max_length"), utterance("max_length"), utterance("silence"))
    speech, _, _, _ = make_input(recorder, FakeTranscriber(NOISE, NOISE, said("네")))
    assert speech.listen() == "네"
    assert recorder.recalibrations == 1


def test_session_runs_on_speech_input() -> None:
    """The agent gets recognized text exactly like typed text."""
    screen = FakeScreen(window(button("주문하기")))
    llm = FakeLlm(reply("어떤 음료를 드릴까요?"))
    output = RecordingOutput()
    agent = Agent(screen, llm, output, agent_config(), FAST_SCREEN)
    presses = [True, False]
    speech = SpeechInput(
        FakeRecorder(utterance()),
        FakeTranscriber(said("주문할게요")),
        output,
        push_to_talk=lambda: presses.pop(0),
        notify=lambda _: None,
    )
    run_session(agent, speech, output)
    assert output.messages == [("say", GREETING), ("ask", ("어떤 음료를 드릴까요?", []))]
    assert "주문할게요" in str(llm.requests[0][0])
