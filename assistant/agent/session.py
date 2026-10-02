"""The listen -> handle loop. Runs in whatever thread calls it (a worker thread in the app)."""

from __future__ import annotations

import threading

from assistant.agent.loop import Agent
from assistant.userio.base import AssistantState, UserInput, UserOutput

GREETING = "안녕하세요! 키오스크 주문을 도와드릴게요. 무엇을 드릴까요?"
RESET_MESSAGE = "대화를 처음부터 다시 시작할게요. 무엇을 도와드릴까요?"
QUIT_COMMANDS = {"/quit", "/exit"}
RESET_COMMAND = "/reset"


def run_session(
    agent: Agent,
    user_input: UserInput,
    output: UserOutput,
    stop: threading.Event | None = None,
) -> None:
    """Greet, then handle user messages until input ends, a quit command, or `stop` is set."""
    stop = stop or threading.Event()
    output.say(GREETING)
    while not stop.is_set():
        output.set_state(AssistantState.LISTENING)
        text = user_input.listen()
        if text is None:
            break
        text = text.strip()
        if not text:
            continue
        if text in QUIT_COMMANDS:
            break
        if text == RESET_COMMAND:
            agent.reset()
            output.say(RESET_MESSAGE)
            continue
        agent.handle(text)
    output.set_state(AssistantState.IDLE)
