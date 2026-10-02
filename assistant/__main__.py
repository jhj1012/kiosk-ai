"""Run the text assistant: `uv run python -m assistant [--debug] [--model NAME]`.

Type Korean in the terminal; the assistant operates the kiosk window and answers. The agent
runs in a worker thread (the main thread stays free, as a Qt overlay will need it later).
Commands: /reset starts a new conversation, /quit exits.
"""

from __future__ import annotations

import argparse
import logging
import sys
import threading
from dataclasses import replace
from datetime import datetime
from pathlib import Path

from assistant.agent.loop import Agent
from assistant.agent.session import run_session
from assistant.config import Config, ConfigError, load_config
from assistant.llm.client import LlmError, OllamaChatModel
from assistant.screen.base import WindowNotFoundError
from assistant.screen.uia import UiaScreen
from assistant.userio.console import ConsoleInput, ConsoleOutput

LOG_DIR = Path(__file__).resolve().parent.parent / "logs"
log = logging.getLogger("assistant")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Kiosk assistant (text mode)")
    parser.add_argument(
        "--debug", action="store_true", help="print screens, model answers and actions"
    )
    parser.add_argument("--model", help="Ollama model to use instead of configs/models.yaml")
    args = parser.parse_args(argv)
    _utf8_console()

    try:
        config = load_config()
    except ConfigError as e:
        print(f"Config error: {e}", file=sys.stderr)
        return 2
    if args.model:
        config = replace(config, llm=replace(config.llm, model=args.model))
    log_path = _setup_logging(args.debug)
    log.info("model %s, window %r", config.llm.model, config.screen.window_title)
    print(f"모델: {config.llm.model} | 창: {config.screen.window_title} | 로그: {log_path}")

    try:
        llm = OllamaChatModel(config.llm)
        llm.check_ready()
        print("모델을 불러오는 중...", flush=True)
        llm.warm_up()
    except LlmError as e:
        print(f"LLM error: {e}", file=sys.stderr)
        return 1

    failed = threading.Event()
    worker = threading.Thread(
        target=_run_agent, args=(config, llm, args.debug, failed), name="agent", daemon=True
    )
    worker.start()
    try:
        while worker.is_alive():
            worker.join(0.2)
    except KeyboardInterrupt:
        print("\n종료합니다.")
        return 130
    return 1 if failed.is_set() else 0


def _run_agent(config: Config, llm: OllamaChatModel, debug: bool, failed: threading.Event) -> None:
    """Agent thread: owns the UIA (COM) objects from attach to exit."""
    output = ConsoleOutput(show_states=debug)
    try:
        screen = UiaScreen(config.screen)
        screen.attach()
        agent = Agent(screen, llm, output, config.agent, config.screen)
        run_session(agent, ConsoleInput(), output)
    except WindowNotFoundError as e:
        print(f"Screen error: {e}", file=sys.stderr)
        failed.set()
    except Exception:
        log.exception("agent crashed")
        failed.set()


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
    for noisy in ("httpx", "httpcore", "comtypes"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    return path


def _utf8_console() -> None:
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
