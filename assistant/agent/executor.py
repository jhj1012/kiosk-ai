"""Carry out the model's actions on the screen, one by one.

Element numbers refer to the snapshot the model saw. After each action the screen is read
again and the next target is found by its UIA RuntimeId; if it is gone (the screen changed),
the rest of the batch is skipped and the model decides again with the new screen.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from assistant.agent.decision import ActionRequest
from assistant.agent.payment import PaymentGate
from assistant.screen.base import ActionError, Screen
from assistant.screen.model import Element, Pattern, Snapshot

log = logging.getLogger(__name__)

KEY_PAUSE_S = 0.05  # between on-screen keypad presses


@dataclass
class Execution:
    snapshot: Snapshot  # the settled screen after the actions
    lines: list[str]  # what happened, one line per action, for the model
    failed: bool = False

    def report(self) -> str:
        return "RESULT:\n" + "\n".join(f"- {line}" for line in self.lines)


class _Stop(Exception):
    """Stops the batch; the message goes to the model."""


class Executor:
    def __init__(
        self,
        screen: Screen,
        gate: PaymentGate,
        *,
        settle: Callable[[], Snapshot],
        pause: Callable[[float], None] = time.sleep,
    ) -> None:
        self.screen = screen
        self.gate = gate
        self._settle = settle
        self._pause = pause

    def run(self, actions: Sequence[ActionRequest], seen: Snapshot) -> Execution:
        """Run `actions` that refer to snapshot `seen`."""
        lines: list[str] = []
        current = seen
        for index, action in enumerate(actions):
            try:
                current, line = self._run_one(action, seen, current)
            except _Stop as stop:
                lines.append(str(stop))
                skipped = len(actions) - index - 1
                if skipped:
                    lines.append(f"SKIPPED the remaining {skipped} action(s).")
                log.info("action stopped: %s", stop)
                return Execution(self._settle(), lines, failed=True)
            lines.append(line)
            log.info("action: %s", line)
        return Execution(current, lines)

    # ----- one action -----

    def _run_one(
        self, action: ActionRequest, seen: Snapshot, current: Snapshot
    ) -> tuple[Snapshot, str]:
        if action.do == "wait":
            self._pause(action.seconds)
            return self._settle(), f"waited {action.seconds} s"
        if action.do == "type_text":
            return self._type(action, seen, current)
        assert action.ref is not None  # checked by parse_decision
        element = self._resolve(action.ref, seen, current)
        if action.do == "scroll":
            self._call(self.screen.scroll, element, action.direction)
            return self._settle(), f"scrolled {element.label} {action.direction}"
        if action.do == "unselect":
            return self._set_checked(element, False, current)
        if action.do == "select" or element.is_toggleable:
            return self._set_checked(element, True, current)
        return self._click(element, action.times)

    def _resolve(self, ref: int, seen: Snapshot, current: Snapshot) -> Element:
        original = seen.by_ref(ref)
        if original is None:
            raise _Stop(f"ERROR: [{ref}] is not on the screen.")
        element = original if current is seen else current.find(original.runtime_id)
        if element is None:
            raise _Stop(f"SKIPPED {original.label}: the screen changed, it is no longer there.")
        if not element.enabled:
            raise _Stop(f"ERROR: {element.label} is disabled now.")
        return element

    def _click(self, element: Element, times: int) -> tuple[Snapshot, str]:
        current: Snapshot | None = None
        for count in range(times):
            if current is not None:
                again = current.find(element.runtime_id)
                if again is None or not again.enabled:
                    raise _Stop(
                        f"ERROR: {element.label} was pressed {count} of {times} times; "
                        "then it was gone or disabled."
                    )
                element = again
            self._press(element)
            current = self._settle()
        assert current is not None
        suffix = f" {times} times" if times > 1 else ""
        return current, f"pressed {element.label}{suffix}"

    def _press(self, element: Element) -> None:
        reason = self.gate.blocked_reason(element)
        if reason:
            raise _Stop(reason)
        if Pattern.INVOKE in element.patterns:
            self._call(self.screen.invoke, element)
        elif Pattern.SELECT in element.patterns:
            self._call(self.screen.select, element)
        elif Pattern.TOGGLE in element.patterns:
            self._call(self.screen.toggle, element)
        else:
            log.warning("no UIA pattern for %s, using the mouse", element.label)
            self._call(self.screen.click, element)

    def _set_checked(self, element: Element, on: bool, current: Snapshot) -> tuple[Snapshot, str]:
        word = "selected" if on else "turned off"
        if element.is_toggleable:
            if element.checked == on:
                return current, f"{element.label} was already {'selected' if on else 'off'}"
            self._call(self.screen.toggle, element)
            after_screen = self._settle()
            after = after_screen.find(element.runtime_id)
            if after is not None and after.checked is not None and after.checked != on:
                if on:
                    raise _Stop(f"ERROR: {element.label} did not become selected.")
                # A single-choice group keeps one choice on; selecting another one switches it.
                # Not an error: the batch usually selects the other choice next.
                return after_screen, (
                    f"NOTE: {element.label} stays selected; in a single-choice group, select "
                    "another choice instead of turning this one off"
                )
            return after_screen, f"{word} {element.label}"
        if not on:
            raise _Stop(f"ERROR: {element.label} is not a choice that can be turned off.")
        if Pattern.SELECT in element.patterns:
            self._call(self.screen.select, element)
            return self._settle(), f"{word} {element.label}"
        return self._click(element, 1)  # a plain button: pressing it is how it is chosen

    def _type(
        self, action: ActionRequest, seen: Snapshot, current: Snapshot
    ) -> tuple[Snapshot, str]:
        target = self._resolve(action.ref, seen, current) if action.ref is not None else None
        if target is None:
            fields = [
                e
                for e in current.elements
                if e.ref is not None
                and Pattern.VALUE in e.patterns
                and e.kind in {"Edit", "ComboBox"}
            ]
            target = fields[0] if len(fields) == 1 else None
        if target is not None and Pattern.VALUE in target.patterns:
            self._call(self.screen.set_value, target, action.text)
            return self._settle(), f'typed "{action.text}" into {target.label}'
        try:
            keys = plan_keypad(action.text, current)
        except ValueError as e:
            raise _Stop(f"ERROR: {e}") from e
        for key in keys:
            self._press(key)
            self._pause(KEY_PAUSE_S)
        return self._settle(), f'typed "{action.text}" with the on-screen keys'

    def _call(self, method: Callable[..., None], *args: object) -> None:
        try:
            method(*args)
        except ActionError as e:
            raise _Stop(f"ERROR: {e}") from e


def plan_keypad(text: str, snapshot: Snapshot) -> list[Element]:
    """Map each character of `text` to an on-screen key button.

    A key matches if its name is the character ("1") or ends with it ("숫자 1"). Spaces and
    dashes are skipped (phone numbers). Raises ValueError if a character has no single key.
    """
    buttons = [e for e in snapshot.elements if e.ref is not None and e.kind == "Button"]
    keys: list[Element] = []
    for char in text:
        if char.isspace() or char == "-":
            continue
        exact = [b for b in buttons if b.name == char]
        candidates = exact or [b for b in buttons if b.name.split()[-1:] == [char]]
        if len(candidates) != 1:
            problem = "no on-screen key" if not candidates else "more than one on-screen key"
            raise ValueError(f'{problem} for "{char}"')
        keys.append(candidates[0])
    if not keys:
        raise ValueError("nothing to type")
    return keys
