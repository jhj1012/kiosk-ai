"""JSON schemas for the model's answers, built for the current screen.

Ollama turns the schema into a grammar, so the model can only produce valid JSON, and element
numbers are limited to the ones that exist on the screen it was shown.
"""

from __future__ import annotations

from typing import Any

from assistant.screen.model import Pattern, Snapshot

NOTE_MAX = 150  # "screen" and "todo": short reasoning written before deciding
ASK_MAX = 6  # "need_to_ask": required choices on the screen the customer has not given
MESSAGE_MAX = 400
TEXT_MAX = 40
MAX_ACTIONS = 12
MAX_TIMES = 20
MAX_WAIT_S = 5
REPLY_KINDS = ("ask", "tell", "confirm")


def decision_schema(snapshot: Snapshot) -> dict[str, Any]:
    """Either act on the screen, or reply to the customer (ending the turn)."""
    return {"anyOf": [_act_schema(snapshot), reply_schema(snapshot)]}


def reply_schema(snapshot: Snapshot) -> dict[str, Any]:
    """Only a reply: used when the step limit is reached."""
    return _object(
        screen=_string(NOTE_MAX),
        todo=_string(NOTE_MAX),
        need_to_ask=_need_to_ask(),
        next={"const": "reply"},
        kind={"type": "string", "enum": list(REPLY_KINDS)},
        message=_string(MESSAGE_MAX),
        choices=_ref_list(_control_refs(snapshot), max_items=MAX_ACTIONS),
    )


def _act_schema(snapshot: Snapshot) -> dict[str, Any]:
    controls = _control_refs(snapshot)
    edits = [
        e.ref
        for e in snapshot.elements
        if e.ref is not None and Pattern.VALUE in e.patterns and e.kind in {"Edit", "ComboBox"}
    ]
    variants: list[dict[str, Any]] = []
    if controls:
        variants.append(
            _object(
                do={"const": "click"},
                id=_ref(controls),
                times={"type": "integer", "minimum": 1, "maximum": MAX_TIMES},
            )
        )
        variants.append(
            _object(do={"type": "string", "enum": ["select", "unselect"]}, id=_ref(controls))
        )
    if edits:
        variants.append(_object(do={"const": "type_text"}, id=_ref(edits), text=_string(TEXT_MAX)))
    else:
        variants.append(_object(do={"const": "type_text"}, text=_string(TEXT_MAX)))
    if snapshot.scroll_refs:
        variants.append(
            _object(
                do={"const": "scroll"},
                id=_ref(snapshot.scroll_refs),
                direction={"type": "string", "enum": ["up", "down"]},
            )
        )
    variants.append(
        _object(
            do={"const": "wait"}, seconds={"type": "integer", "minimum": 1, "maximum": MAX_WAIT_S}
        )
    )
    return _object(
        screen=_string(NOTE_MAX),
        todo=_string(NOTE_MAX),
        need_to_ask=_need_to_ask(),
        next={"const": "act"},
        actions={
            "type": "array",
            "items": {"anyOf": variants},
            "minItems": 1,
            "maxItems": MAX_ACTIONS,
        },
    )


def _control_refs(snapshot: Snapshot) -> list[int]:
    return [e.ref for e in snapshot.elements if e.ref is not None and not e.is_region]


def _object(**properties: dict[str, Any]) -> dict[str, Any]:
    """An object whose properties are all required, in this order."""
    return {"type": "object", "properties": properties, "required": list(properties)}


def _string(max_length: int) -> dict[str, Any]:
    return {"type": "string", "maxLength": max_length}


def _need_to_ask() -> dict[str, Any]:
    return {"type": "array", "items": _string(30), "maxItems": ASK_MAX}


def _ref(refs: list[int]) -> dict[str, Any]:
    return {"type": "integer", "enum": refs}


def _ref_list(refs: list[int], max_items: int) -> dict[str, Any]:
    if not refs:
        return {"type": "array", "maxItems": 0}
    return {"type": "array", "items": _ref(refs), "maxItems": max_items}
