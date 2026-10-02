"""Parse and validate the model's JSON answer for one step."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from assistant.llm.schema import MAX_TIMES, MAX_WAIT_S, REPLY_KINDS
from assistant.screen.model import Element, Snapshot

ACTIONS = ("click", "select", "unselect", "type_text", "scroll", "wait")
CHOICE_ACTIONS = ("select", "unselect", "scroll", "wait")  # allowed while choices are missing


class DecisionError(ValueError):
    """The answer is unusable. The message is shown to the model so it can try again."""


@dataclass(frozen=True)
class ActionRequest:
    do: str
    ref: int | None = None
    times: int = 1
    text: str = ""
    direction: str = "down"
    seconds: int = 1


@dataclass(frozen=True)
class Reply:
    kind: str  # "ask", "tell" or "confirm"
    message: str
    choices: tuple[int, ...] = ()


@dataclass(frozen=True)
class Decision:
    thought: str
    actions: tuple[ActionRequest, ...] = ()
    reply: Reply | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> str:
        """Compact JSON to keep in the conversation history."""
        return json.dumps(self.raw, ensure_ascii=False)


def parse_decision(text: str, snapshot: Snapshot) -> Decision:
    """Turn the model's answer into a Decision, checking numbers against `snapshot`."""
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise DecisionError(f"Your answer was not valid JSON ({e.msg}). Keep it short.") from e
    if not isinstance(data, dict):
        raise DecisionError("Your answer must be a JSON object.")
    thought = " | ".join(str(data[k]) for k in ("screen", "todo", "thought") if data.get(k))
    next_step = data.get("next")
    if next_step == "reply":
        return Decision(thought, reply=_parse_reply(data, snapshot), raw=data)
    if next_step == "act":
        actions = data.get("actions")
        if not isinstance(actions, list) or not actions:
            raise DecisionError('"act" needs at least one action.')
        parsed = tuple(_parse_action(a, snapshot) for a in actions)
        missing = [m for m in _strings(data.get("missing")) if _on_screen(m, snapshot)]
        if missing and not all(_is_choice(a, snapshot) for a in parsed):
            # Pressing on (add to cart, next, ...) while a required choice is open would
            # decide it for the customer with the screen's default.
            raise DecisionError(
                f"You listed missing choices ({', '.join(missing)}). Do not press anything else "
                "yet: only select what the customer already told you, then ask about the rest."
            )
        return Decision(thought, actions=parsed, raw=data)
    raise DecisionError('"next" must be "act" or "reply".')


def _parse_reply(data: dict[str, Any], snapshot: Snapshot) -> Reply:
    message = clean_message(str(data.get("message", "")))
    if not message:
        raise DecisionError('"reply" needs a "message" for the customer.')
    kind = data.get("kind")
    if kind not in REPLY_KINDS:
        kind = "ask" if message.rstrip().endswith("?") else "tell"
    valid = set(snapshot.refs)
    choices = data.get("choices") or []
    refs = (
        tuple(c for c in choices if isinstance(c, int) and c in valid)
        if isinstance(choices, list)
        else ()
    )
    return Reply(kind, message, tuple(dict.fromkeys(refs)))


def _parse_action(item: Any, snapshot: Snapshot) -> ActionRequest:
    if not isinstance(item, dict):
        raise DecisionError("Each action must be a JSON object.")
    do = item.get("do")
    if do not in ACTIONS:
        raise DecisionError(f'Unknown action "{do}". Use one of: {", ".join(ACTIONS)}.')
    if do == "wait":
        return ActionRequest(do, seconds=_clamp(item.get("seconds"), 1, MAX_WAIT_S))
    if do == "type_text":
        text = str(item.get("text", "")).strip()
        if not text:
            raise DecisionError('"type_text" needs a "text".')
        ref = item.get("id")
        if ref is not None:
            _check_ref(ref, snapshot)
        return ActionRequest(do, ref=ref, text=text)
    ref = item.get("id")
    element = _check_ref(ref, snapshot)
    if do == "scroll":
        if element.scroll is None:
            raise DecisionError(f"[{ref}] cannot be scrolled.")
        direction = item.get("direction")
        return ActionRequest(do, ref=ref, direction="up" if direction == "up" else "down")
    if element.is_region:
        raise DecisionError(f"[{ref}] is a group, not a control. Use a number of a control in it.")
    times = _clamp(item.get("times"), 1, MAX_TIMES) if do == "click" else 1
    return ActionRequest(do, ref=ref, times=times)


def _strings(value: Any) -> list[str]:
    return [str(v).strip() for v in value if str(v).strip()] if isinstance(value, list) else []


def _on_screen(choice: str, snapshot: Snapshot) -> bool:
    """True if a word of `choice` (e.g. "사이즈" of "사이즈/크기") appears on the screen.

    Only those entries are enforced: the model sometimes lists choices of a later screen.
    """
    words = [w for w in re.split(r"[\s/,()]+", choice) if len(w) >= 2]
    return any(w in e.name for w in words for e in snapshot.elements)


def _is_choice(action: ActionRequest, snapshot: Snapshot) -> bool:
    """True for actions that only set choices (clicking a check box selects it)."""
    if action.do in CHOICE_ACTIONS:
        return True
    element = snapshot.by_ref(action.ref) if action.ref is not None else None
    return action.do == "click" and element is not None and element.is_toggleable


def _check_ref(ref: Any, snapshot: Snapshot) -> Element:
    element = snapshot.by_ref(ref) if isinstance(ref, int) else None
    if element is None:
        raise DecisionError(f"[{ref}] is not a number on the CURRENT SCREEN.")
    return element


def _clamp(value: Any, low: int, high: int) -> int:
    if not isinstance(value, int):
        return low
    return max(low, min(high, value))


def clean_message(message: str) -> str:
    """Remove element numbers like "[7]" the model may have copied from the screen."""
    return re.sub(r"\s*\[\d+\]\s*", " ", message).strip()
