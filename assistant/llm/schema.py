"""JSON schemas for the model's answers, built for the current screen.

Gemini's structured output follows the schema, so answers always parse, and targets are
limited to the controls on the screen the model was shown. Targets are the controls' names,
not their numbers: the model then picks what it means by name, and does not copy stale
numbers from earlier answers (seen in E2E tests).

Only JSON Schema keywords that Gemini supports are used (no `const`, no string lengths), and
the root is a plain object: one answer either acts ("next": "act" with "actions") or replies
("next": "reply" with "message"); `decision.py` checks the fields that belong to each.
"""

from __future__ import annotations

from typing import Any

from assistant.screen.model import Pattern, Snapshot

ASK_MAX = 6  # "need_to_ask": required choices on the screen the customer has not given
MAX_ACTIONS = 6  # real batches are ~4 (choices, quantity, add); long ones were garbage
MAX_CHOICES = 10
MAX_TIMES = 20
MAX_WAIT_S = 5
REPLY_KINDS = ("ask", "tell", "confirm")


def decision_schema(snapshot: Snapshot) -> dict[str, Any]:
    """Either act on the screen, or reply to the customer (ending the turn)."""
    return _object(
        _notes(),
        next=_enum(["act", "reply"], "act: use the screen now. reply: talk to the customer."),
        actions={
            "type": "array",
            "description": 'Only for "act": the actions to do now, in order.',
            "items": {"anyOf": _action_variants(snapshot)},
            "maxItems": MAX_ACTIONS,
        },
        **_reply_fields(snapshot, 'Only for "reply": '),
        required=["screen", "todo", "need_to_ask", "next"],
    )


def reply_schema(snapshot: Snapshot) -> dict[str, Any]:
    """Only a reply: used when the step limit is reached."""
    return _object(
        _notes(),
        next=_enum(["reply"], "Always reply now."),
        **_reply_fields(snapshot, ""),
    )


def _notes() -> dict[str, Any]:
    return {
        "screen": _string("A few English words: what the CURRENT SCREEN is for."),
        "todo": _string("What the customer asked for that is not done yet, with quantities."),
        "need_to_ask": {
            "type": "array",
            "description": "Required choices on this screen the customer has not said yet.",
            "items": {"type": "string"},
            "maxItems": ASK_MAX,
        },
    }


def _reply_fields(snapshot: Snapshot, prefix: str) -> dict[str, Any]:
    return {
        "kind": _enum(list(REPLY_KINDS), f"{prefix}ask, tell, or confirm (payment read-back)."),
        "message": _string(f"{prefix}what you say to the customer, in short polite Korean."),
        "choices": _target_list(_control_keys(snapshot)),
    }


def _action_variants(snapshot: Snapshot) -> list[dict[str, Any]]:
    controls = _control_keys(snapshot)
    edits = [
        e.key
        for e in snapshot.elements
        if e.ref is not None and Pattern.VALUE in e.patterns and e.kind in {"Edit", "ComboBox"}
    ]
    scrollable = [e.key for e in snapshot.elements if e.scroll is not None and e.ref is not None]
    variants: list[dict[str, Any]] = []
    if controls:
        variants.append(
            _object(
                do=_enum(["click"]),
                target=_enum(controls),
                times={"type": "integer", "minimum": 1, "maximum": MAX_TIMES},
            )
        )
        variants.append(_object(do=_enum(["select", "unselect"]), target=_enum(controls)))
    if edits:
        variants.append(_object(do=_enum(["type_text"]), target=_enum(edits), text=_string()))
    else:
        variants.append(_object(do=_enum(["type_text"]), text=_string()))
    if scrollable:
        variants.append(
            _object(do=_enum(["scroll"]), target=_enum(scrollable), direction=_enum(["up", "down"]))
        )
    variants.append(
        _object(
            do=_enum(["wait"]), seconds={"type": "integer", "minimum": 1, "maximum": MAX_WAIT_S}
        )
    )
    return variants


def _control_keys(snapshot: Snapshot) -> list[str]:
    return [e.key for e in snapshot.elements if e.ref is not None and not e.is_region]


def _object(
    extra: dict[str, Any] | None = None,
    *,
    required: list[str] | None = None,
    **properties: dict[str, Any],
) -> dict[str, Any]:
    """An object with these properties, in this order; all required unless `required` says."""
    props = {**(extra or {}), **properties}
    return {
        "type": "object",
        "properties": props,
        "required": list(props) if required is None else required,
    }


def _string(description: str = "") -> dict[str, Any]:
    schema: dict[str, Any] = {"type": "string"}
    if description:
        schema["description"] = description
    return schema


def _enum(values: list[str], description: str = "") -> dict[str, Any]:
    schema: dict[str, Any] = {"type": "string", "enum": values}
    if description:
        schema["description"] = description
    return schema


def _target_list(keys: list[str]) -> dict[str, Any]:
    description = "Names of the controls the customer can choose from now, or []."
    items = _enum(keys) if keys else {"type": "string"}
    return {
        "type": "array",
        "description": description,
        "items": items,
        "maxItems": MAX_CHOICES if keys else 0,
    }
