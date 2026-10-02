"""Run the assistant: `uv run python -m assistant [--voice] [--debug] [--model NAME]`.

Type Korean in the terminal (default), or speak into the microphone with --voice; the
assistant operates the kiosk window and answers. The agent runs in a worker thread (the main
thread stays free, as a Qt overlay will need it later).
Typed commands: /reset starts a new conversation, /quit exits. In voice mode Ctrl+C exits.
"""

from __future__ import annotations

import argparse
import logging
import sys
import threading
import time
from dataclasses import replace
from datetime import datetime
from pathlib import Path

from assistant.agent.loop import Agent
from assistant.agent.session import run_session
from assistant.audio.duplex import SpeakingGate
from assistant.audio.mic import Microphone
from assistant.audio.recorder import UtteranceRecorder
from assistant.config import Config, ConfigError, load_config, load_env_file
from assistant.llm.client import GeminiChatModel, LlmError
from assistant.screen.base import WindowNotFoundError
from assistant.screen.uia import UiaScreen
from assistant.stt.transcriber import GeminiTranscriber, vocabulary
from assistant.userio.console import ConsoleInput, ConsoleOutput
from assistant.userio.speech import SpeechInput

LOG_DIR = Path(__file__).resolve().parent.parent / "logs"
RECORDINGS_DIR = LOG_DIR.parent / "recordings"  # git-ignored; only with --save-audio
WINDOW_RETRY_S = 5.0  # how often to look for the kiosk window while it is missing
log = logging.getLogger("assistant")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Kiosk assistant")
    parser.add_argument(
        "--voice", action="store_true", help="speak into the microphone instead of typing"
    )
    parser.add_argument(
        "--push-to-talk",
        action="store_true",
        help="with --voice: press Enter before speaking (developer mode)",
    )
    parser.add_argument(
        "--save-audio",
        action="store_true",
        help="with --voice: save every utterance to recordings/ (debugging)",
    )
    parser.add_argument(
        "--debug", action="store_true", help="print screens, model answers and actions"
    )
    parser.add_argument("--model", help="Gemini model to use instead of configs/models.yaml")
    args = parser.parse_args(argv)
    if (args.push_to_talk or args.save_audio) and not args.voice:
        parser.error("--push-to-talk and --save-audio need --voice")
    _utf8_console()

    try:
        config = load_config()
    except ConfigError as e:
        print(f"Config error: {e}", file=sys.stderr)
        return 2
    if args.model:
        config = replace(config, llm=replace(config.llm, model=args.model))
    log_path = _setup_logging(args.debug)
    loaded = load_env_file()
    if loaded:
        log.info("loaded from .env: %s", ", ".join(loaded))
    log.info("model %s, window %r", config.llm.model, config.screen.window_title)
    print(f"모델: {config.llm.model} | 창: {config.screen.window_title} | 로그: {log_path}")

    try:
        llm = GeminiChatModel(config.llm)
        llm.check_ready()
    except LlmError as e:
        print(f"LLM error: {e}", file=sys.stderr)
        return 1
    stt = None
    if args.voice:
        try:
            stt = GeminiChatModel(config.stt.llm_config(config.llm.api_key_env))
            stt.check_ready()
        except LlmError as e:
            print(f"Speech recognition error: {e}", file=sys.stderr)
            return 1
        log.info("speech recognition: %s", config.stt.model)
        print(f"음성 인식: {config.stt.model} (Ctrl+C로 종료)")

    failed = threading.Event()
    worker = threading.Thread(
        target=_run_agent, args=(config, llm, stt, args, failed), name="agent", daemon=True
    )
    worker.start()
    try:
        while worker.is_alive():
            worker.join(0.2)
    except KeyboardInterrupt:
        print("\n종료합니다.")
        return 130
    return 1 if failed.is_set() else 0


def _run_agent(
    config: Config,
    llm: GeminiChatModel,
    stt: GeminiChatModel | None,
    args: argparse.Namespace,
    failed: threading.Event,
) -> None:
    """Agent thread: owns the UIA (COM) objects from attach to exit."""
    output = ConsoleOutput(show_states=args.debug)
    try:
        screen = UiaScreen(config.screen)
        _wait_for_window(screen)
        agent = Agent(screen, llm, output, config.agent, config.screen)
        if stt is None:
            run_session(agent, ConsoleInput(), output)
            return
        speech = _speech_input(config, stt, screen, output, args)
        try:
            run_session(agent, speech, output)
        finally:
            speech.close()
    except Exception:
        log.exception("agent crashed")
        failed.set()


def _speech_input(
    config: Config,
    stt: GeminiChatModel,
    screen: UiaScreen,
    output: ConsoleOutput,
    args: argparse.Namespace,
) -> SpeechInput:
    # Half-duplex: the speech output (TTS phase) must wrap playback in `gate.speaking()`, so
    # the microphone ignores the assistant's own voice.
    gate = SpeakingGate(tail_s=config.audio.echo_tail_ms / 1000)
    recorder = UtteranceRecorder(Microphone(config.audio, gate), config.audio)
    hints = None
    if config.stt.vocabulary_hints:
        # Called from listen(), i.e. in this (the agent's) thread, as UiaScreen requires.
        def hints() -> list[str]:
            return vocabulary(screen.read())

    return SpeechInput(
        recorder,
        GeminiTranscriber(stt),
        output,
        hints=hints,
        push_to_talk=_wait_for_enter if args.push_to_talk else None,
        save_dir=RECORDINGS_DIR if args.save_audio else None,
        verbose=args.debug,
    )


def _wait_for_enter() -> bool:
    try:
        input()
    except EOFError:
        return False
    return True


def _wait_for_window(screen: UiaScreen) -> None:
    """Attach to the kiosk window, waiting until it appears (the assistant runs all day)."""
    told = False
    while True:
        try:
            screen.attach()
            if told:
                print("키오스크 창을 찾았어요.", flush=True)
            return
        except WindowNotFoundError as e:
            if not told:
                print(f"Screen: {e}\n키오스크 창을 기다리는 중... (Ctrl+C로 종료)", flush=True)
                told = True
            time.sleep(WINDOW_RETRY_S)


def _setup_logging(debug: bool) -> Path:
    LOG_DIR.mkdir(exist_ok=True)
    path = LOG_DIR / f"session-{datetime.now():%Y%m%d-%H%M%S}.log"
    file_handler = logging.FileHandler(path, encoding="utf-8")
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    )
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    root.addHandler(file_handler)
    if debug:
        console = logging.StreamHandler(sys.stdout)
        console.setFormatter(logging.Formatter("    | %(message)s"))
        console.setLevel(logging.DEBUG)
        log.addHandler(console)  # only the assistant's own loggers on screen
    for noisy in ("httpx", "httpcore", "comtypes", "google_genai"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    return path


def _utf8_console() -> None:
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
