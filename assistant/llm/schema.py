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

from assistant.screen.model import Snapshot

ASK_MAX = 6  # "need_to_ask": required choices on the screen the customer has not given
MAX_ACTIONS = 6  # real batches are ~4 (choices, quantity, add); long ones were garbage
MAX_CHOICES = 10
MAX_TIMES = 20
MAX_WAIT_S = 5
REPLY_KINDS = ("ask", "tell", "confirm", "new_customer")


def decision_schema(snapshot: Snapshot) -> dict[str, Any]:
    """Either act on the screen, or reply to the customer (ending the turn)."""
    return _object(
        _notes(),
        next=_enum(["act", "reply"], "act: use the screen now. reply: talk to the customer."),
        actions={
            "type": "array",
            "description": 'Only for "act": the actions to do now, in order.',
            "items": _action_item(snapshot),
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
    message = "What you say to the customer, in short polite Korean."
    if prefix:
        message += ' With "act": empty, or the order read-back when pressing the final pay button.'
    return {
        "kind": _enum(
            list(REPLY_KINDS),
            f"{prefix}ask, tell, confirm (only before cancelling the order), or new_customer "
            "(ask whether the speaker is a new customer).",
        ),
        "message": _string(message),
        "choices": _target_list(_control_keys(snapshot)),
    }


def _action_item(snapshot: Snapshot) -> dict[str, Any]:
    """One flat action object; `decision.py` checks which fields each action needs.

    Separate anyOf variants per action repeat the list of names and made Gemini reject the
    schema as too complex (400 INVALID_ARGUMENT) on screens with ~18 controls.
    """
    targets = [e.key for e in snapshot.elements if e.ref is not None]  # controls and regions
    actions = (
        ["click", "select", "unselect"]
        if any(not e.is_region for e in snapshot.elements if e.ref)
        else []
    )
    actions += ["type_text"]
    if snapshot.scroll_refs:
        actions.append("scroll")
    actions.append("wait")
    properties: dict[str, Any] = {"do": _enum(actions)}
    if targets:
        properties["target"] = _enum(targets, "Exact name of the control (not for wait).")
    properties["times"] = {"type": "integer", "minimum": 1, "maximum": MAX_TIMES}
    properties["text"] = _string("Only for type_text.")
    properties["direction"] = _enum(["up", "down"], "Only for scroll.")
    properties["seconds"] = {"type": "integer", "minimum": 1, "maximum": MAX_WAIT_S}
    return {"type": "object", "properties": properties, "required": ["do"]}


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
