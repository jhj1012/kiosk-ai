"""Helpers to build fake UI Automation trees and snapshots for tests."""

from __future__ import annotations

import itertools

from assistant.screen.model import Pattern, Rect, Snapshot
from assistant.screen.reader import RangeInfo, RawNode, build_snapshot

_ids = itertools.count(1)
WINDOW = Rect(0, 0, 600, 900)


def _rid() -> tuple[int, ...]:
    return (42, next(_ids))


def button(name: str, *, enabled: bool = True, rect: Rect | None = None) -> RawNode:
    return RawNode(
        "Button",
        name,
        enabled=enabled,
        rect=rect or Rect(10, 10, 100, 50),
        runtime_id=_rid(),
        patterns=frozenset({Pattern.INVOKE}),
    )


def check(name: str, on: bool = False, *, rect: Rect | None = None) -> RawNode:
    return RawNode(
        "CheckBox",
        name,
        rect=rect or Rect(10, 10, 100, 50),
        runtime_id=_rid(),
        patterns=frozenset({Pattern.INVOKE, Pattern.TOGGLE}),
        toggle_state=on,
    )


def text(name: str, *, rect: Rect | None = None) -> RawNode:
    return RawNode("Text", name, rect=rect or Rect(10, 10, 100, 50), runtime_id=_rid())


def edit(name: str, value: str = "") -> RawNode:
    return RawNode(
        "Edit",
        name,
        rect=Rect(10, 10, 300, 50),
        runtime_id=_rid(),
        patterns=frozenset({Pattern.VALUE}),
        value=value,
    )


def group(name: str, *children: RawNode, rect: Rect | None = None, kind: str = "Group") -> RawNode:
    return RawNode(kind, name, rect=rect or WINDOW, runtime_id=_rid(), children=list(children))


def scrollbar(value: float = 0, maximum: float = 300, *, read_only: bool = False) -> RawNode:
    return RawNode(
        "ScrollBar",
        "",
        rect=Rect(580, 100, 600, 800),
        runtime_id=_rid(),
        patterns=frozenset({Pattern.RANGE}),
        range=RangeInfo(value, 0, maximum, 20, read_only),
    )


def window(*children: RawNode) -> RawNode:
    return RawNode("Window", "Test", rect=WINDOW, runtime_id=_rid(), children=list(children))


def snapshot(*children: RawNode) -> Snapshot:
    return build_snapshot(window(*children), "Test")
