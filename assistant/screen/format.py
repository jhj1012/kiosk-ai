"""Render a Snapshot as the compact text the LLM reads.

Example:

    [1] Button "처음으로"
    <옵션 목록>
      Text "온도 선택"
      [2] CheckBox "온도 HOT +0원 (선택됨)" checked
      [3] CheckBox "온도 ICE +0원" unchecked
    Button "수량 감소" (disabled)
    [4] Button "수량 증가"

Bounding rectangles are kept in the Snapshot but not shown to the LLM.
"""

from __future__ import annotations

from assistant.screen.model import Element, Snapshot

EMPTY_SCREEN = "(nothing readable on the screen)"


def format_element(element: Element) -> str:
    indent = "  " * element.depth
    ref = f"[{element.ref}] " if element.ref is not None else ""
    if element.is_region:
        return f"{indent}{ref}<{element.key or element.name}>{_scroll_hint(element)}"
    line = f'{indent}{ref}{element.kind} "{element.key or element.name}"'
    if element.checked is not None:
        line += " checked" if element.checked else " unchecked"
    if element.value is not None:
        line += f' value="{element.value}"'
    if not element.enabled:
        line += " (disabled)"
    return line


def format_snapshot(snapshot: Snapshot) -> str:
    if not snapshot.elements:
        return EMPTY_SCREEN
    return "\n".join(format_element(e) for e in snapshot.elements)


def _scroll_hint(element: Element) -> str:
    scroll = element.scroll
    if scroll is None:
        return ""
    if scroll.more_above and scroll.more_below:
        return " (scrollable: more above and below)"
    if scroll.more_below:
        return " (scrollable: more below)"
    if scroll.more_above:
        return " (scrollable: more above)"
    return ""
