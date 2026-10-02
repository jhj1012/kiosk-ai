"""The agent: one customer message in, kiosk actions, exactly one message out.

`Agent.handle()` is a plain blocking call with no thread assumptions, so it can run in a
worker thread while a Qt overlay owns the main thread.
"""

from __future__ import annotations

import functools
import json
import logging
import time
from collections.abc import Callable

from assistant.agent.confirm_gate import ConfirmationGate
from assistant.agent.customer import CustomerTracker, Switch
from assistant.agent.decision import Decision, DecisionError, Reply, parse_decision
from assistant.agent.executor import Executor
from assistant.agent.history import Conversation
from assistant.config import AgentConfig, ScreenConfig
from assistant.llm.client import ChatModel, LlmError
from assistant.llm.prompts import (
    CONFIRM_QUESTION,
    CONFIRM_SCHEMA,
    OUT_OF_STEPS,
    PAYMENT_QUESTION,
    SYSTEM_PROMPT,
)
from assistant.llm.schema import decision_schema, reply_schema
from assistant.screen.base import Screen, ScreenError
from assistant.screen.format import format_snapshot
from assistant.screen.model import Element, Snapshot
from assistant.screen.settle import wait_until_settled
from assistant.userio.base import AssistantState, Choice, UserOutput

log = logging.getLogger(__name__)

SCREEN_ERROR_MESSAGE = (
    "죄송해요, 지금 키오스크 화면을 읽을 수 없어요. 키오스크가 켜져 있는지 확인해 주세요."
)
LLM_ERROR_MESSAGE = "죄송해요, 지금 잠시 문제가 생겼어요. 다시 한 번 말씀해 주시겠어요?"
PAYMENT_CONTEXT_MESSAGES = 6  # customer messages the payment check looks at
NEW_CUSTOMER_NOTE = (
    "NOTE: A new customer is talking now. The screen still shows an unfinished order from "
    "someone else. Before using it, ask whether to continue that order or start over."
)
FALLBACK_MESSAGE = "죄송해요, 요청을 끝까지 처리하지 못했어요. 다시 한 번 말씀해 주시겠어요?"


class Agent:
    def __init__(
        self,
        screen: Screen,
        llm: ChatModel,
        output: UserOutput,
        config: AgentConfig,
        screen_config: ScreenConfig,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.screen = screen
        self.llm = llm
        self.output = output
        self.config = config
        self.screen_config = screen_config
        self.conversation = Conversation(SYSTEM_PROMPT, config.history_turns)
        self.gate = ConfirmationGate(
            payment_pattern=config.payment_button_pattern,
            discard_pattern=config.discard_button_pattern,
            guard_payment=config.confirm_before_payment,
        )
        self.executor = Executor(screen, self.gate, settle=self._settle)
        self.customers = CustomerTracker(
            new_customer_after_s=config.new_customer_after_s,
            abandoned_after_s=config.abandoned_after_s,
            clock=clock,
        )
        self.last_reply: Reply | None = None

    def start(self) -> None:
        """Call once when the assistant starts: the kiosk's current screen is its idle screen."""
        self.customers.learn_idle_screen(self._settle())

    def reset(self) -> None:
        """Forget the conversation: the next message comes from a new customer."""
        self.conversation.clear()
        self.last_reply = None
        self.customers.forget()

    def handle(self, text: str) -> Reply:
        """Handle one customer message. Always ends with exactly one say() or ask()."""
        log.info("customer: %s", text)
        self.output.set_state(AssistantState.THINKING)
        snapshot: Snapshot | None = None
        try:
            reply, snapshot = self._run_turn(text)
        except ScreenError as e:
            log.error("screen error: %s", e)
            reply = Reply("tell", SCREEN_ERROR_MESSAGE)
        except LlmError as e:
            log.error("llm error: %s", e)
            reply = Reply("tell", LLM_ERROR_MESSAGE)
        if self.gate.paid_with_read_back:
            # The order read-back given with the pay button comes first, in the same message.
            message = f"{self.gate.paid_with_read_back} {reply.message}".strip()
            reply = Reply(reply.kind, message, reply.choices)
        self._deliver(reply, snapshot)
        self.conversation.end_turn(reply.kind, reply.message)
        self.last_reply = reply
        self.customers.touch()
        self.output.set_state(AssistantState.IDLE)
        return reply

    # ----- one turn -----

    def _run_turn(self, text: str) -> tuple[Reply, Snapshot]:
        snapshot = self._settle()
        switch = self.customers.check(snapshot)
        if switch is not Switch.SAME:
            log.info("new customer (%s): starting a new conversation", switch)
            self.reset()
        self.conversation.add_customer(text)
        if switch is Switch.ABANDONED:
            self.conversation.add_note(NEW_CUSTOMER_NOTE)
        confirm_check = None
        if self.last_reply is not None and self.last_reply.kind == "confirm":
            confirm_check = functools.partial(self._customer_agreed, self.last_reply.message, text)
        self.gate.start_turn(payment_check=self._customer_wants_to_pay, confirm_check=confirm_check)

        # The last thing that went wrong: an invalid answer, or failed actions on a screen.
        # At temperature 0 the model often repeats it exactly; then it is stuck.
        last_failure: object = None
        for step in range(1, self.config.max_steps_per_request + 1):
            decision, answer = self._decide(snapshot, step)
            if decision is None:
                if answer == last_failure:
                    log.warning("model repeated an invalid answer; ending the turn")
                    break
                last_failure = answer
                continue  # the error was noted for the model
            if decision.reply is not None:
                return decision.reply, snapshot
            attempt = (decision.actions, snapshot.signature())
            if attempt == last_failure:
                log.warning("model repeated failed actions; ending the turn")
                break
            self.output.set_state(AssistantState.ACTING)
            self.output.show_elements(self._targets(decision, snapshot))
            self.gate.start_batch(decision.read_back)
            execution = self.executor.run(decision.actions, snapshot)
            self.conversation.add_note(execution.report())
            if self.gate.paid_with_read_back:
                self.conversation.mark_payment()  # this request to pay is used up
            last_failure = attempt if execution.failed else None
            snapshot = execution.snapshot
            self.output.set_state(AssistantState.THINKING)
        else:
            log.warning("step limit (%d) reached", self.config.max_steps_per_request)
        return self._final_reply(snapshot), snapshot

    def _decide(self, snapshot: Snapshot, step: int) -> tuple[Decision | None, str]:
        """Ask the model for the next step. Returns (None, answer) if the answer is unusable."""
        screen_text = format_snapshot(snapshot)
        log.debug("screen (step %d):\n%s", step, screen_text)
        result = self.llm.chat_json(self.conversation.build(screen_text), decision_schema(snapshot))
        log.debug("model: %s", result.text)
        try:
            decision = parse_decision(result.text, snapshot)
        except DecisionError as e:
            log.info("invalid answer: %s", e)
            self.conversation.add_model(result.text[:500])
            self.conversation.add_note(f"ERROR: {e} Answer again.")
            return None, result.text
        log.info("thought: %s", decision.thought)
        self.conversation.add_model(decision.to_json())
        return decision, result.text

    def _final_reply(self, snapshot: Snapshot) -> Reply:
        messages = self.conversation.build(format_snapshot(snapshot), extra_note=OUT_OF_STEPS)
        try:
            result = self.llm.chat_json(messages, reply_schema(snapshot))
            decision = parse_decision(result.text, snapshot)
        except (LlmError, DecisionError) as e:
            log.warning("final reply failed: %s", e)
            decision = None
        if decision is None or decision.reply is None:
            return Reply("tell", FALLBACK_MESSAGE)
        self.conversation.add_model(decision.to_json())
        return decision.reply

    def _customer_agreed(self, question: str, answer: str) -> bool:
        """Did the customer say yes to the assistant's confirm question?"""
        prompt = CONFIRM_QUESTION.format(question=question, answer=answer)
        return self._classify(prompt, f"confirmation {answer!r}")

    def _customer_wants_to_pay(self) -> bool:
        """Has the customer asked to pay, without changing the order since?"""
        recent = self.conversation.customer_messages(PAYMENT_CONTEXT_MESSAGES)
        lines = "\n".join(f"{i}. {m}" for i, m in enumerate(recent, start=1))
        return self._classify(PAYMENT_QUESTION.format(messages=lines), "payment request")

    def _classify(self, prompt: str, what: str) -> bool:
        result = self.llm.chat_json([{"role": "user", "content": prompt}], CONFIRM_SCHEMA)
        try:
            yes = json.loads(result.text).get("answer") == "yes"
        except (json.JSONDecodeError, AttributeError):
            yes = False
        log.info("%s -> %s", what, yes)
        return yes

    # ----- helpers -----

    def _settle(self) -> Snapshot:
        return wait_until_settled(
            self.screen.read,
            timeout_s=self.screen_config.settle_timeout_s,
            interval_s=self.screen_config.poll_interval_s,
        )

    def _deliver(self, reply: Reply, snapshot: Snapshot | None) -> None:
        log.info("reply (%s): %s", reply.kind, reply.message)
        if reply.kind == "tell":
            self.output.say(reply.message)
            return
        choices = []
        for ref in reply.choices:
            element = snapshot.by_ref(ref) if snapshot is not None else None
            if element is not None:
                choices.append(Choice(element.name, element))
        self.output.ask(reply.message, choices)

    @staticmethod
    def _targets(decision: Decision, snapshot: Snapshot) -> list[Element]:
        elements = (snapshot.by_ref(a.ref) for a in decision.actions if a.ref is not None)
        return [e for e in elements if e is not None]
