"""Turn a raw UI Automation tree into a compact Snapshot for the LLM.

The Windows backend (`uia.py`) only copies the tree into `RawNode`s. All filtering happens
here, in plain Python, so it can be unit tested without Windows:

- window chrome (title bar, system menu, minimize/close buttons) is dropped;
- unnamed containers are flattened, named ones become regions shown as `<name>`;
- a region whose only content is another region is merged into it;
- a text that repeats its region's name is dropped (e.g. a cart row and its label);
- scroll bars are not listed; they make their region scrollable instead;
- each element's visible part is clipped by its ancestors (scroll areas do not report
  scrolled-away children as offscreen, so this is computed here);
- enabled controls get a number (`ref`) the LLM uses to act on them.
"""

from __future__ import annotations

import itertools
import re
from collections.abc import Iterator
from dataclasses import dataclass, field, replace

from assistant.screen.model import Element, Pattern, Rect, ScrollInfo, Snapshot

# Subtrees that are never part of the program's own UI.
SKIPPED_KINDS = frozenset({"TitleBar"})
# Controls the assistant can act on. Their children are not listed separately, unless they
# are controls too.
CONTROL_KINDS = frozenset(
    {
        "Button",
        "CheckBox",
        "ComboBox",
        "DataItem",
        "Edit",
        "Hyperlink",
        "ListItem",
        "MenuItem",
        "RadioButton",
        "Slider",
        "Spinner",
        "SplitButton",
        "TabItem",
        "TreeItem",
    }
)
# Read-only content.
TEXT_KINDS = frozenset({"Text", "Image"})
SCROLLBAR_KIND = "ScrollBar"
# Clip area passed to children of an element that is scrolled out of view: hides them too.
_HIDDEN = Rect(0, 0, 0, 0)


@dataclass(frozen=True)
class RangeInfo:
    """RangeValue pattern values (scroll bars, sliders)."""

    value: float
    minimum: float
    maximum: float
    large_change: float
    read_only: bool = False


@dataclass
class RawNode:
    """One UI Automation element, as copied from the live tree."""

    kind: str
    name: str = ""
    enabled: bool = True
    offscreen: bool = False
    rect: Rect | None = None
    runtime_id: tuple[int, ...] = ()
    patterns: frozenset[Pattern] = frozenset()
    toggle_state: bool | None = None
    value: str | None = None
    range: RangeInfo | None = None
    children: list[RawNode] = field(default_factory=list)


@dataclass
class _Item:
    """Intermediate tree node: a leaf element or a region with children."""

    node: RawNode
    name: str
    visible_rect: Rect | None
    is_region: bool = False
    scroll: ScrollInfo | None = None
    children: list[_Item] = field(default_factory=list)


@dataclass
class _ScrollBar:
    """A scroll bar on its way up to the region it scrolls."""

    info: ScrollInfo
    vertical: bool


def clean_name(name: str) -> str:
    """Collapse whitespace and newlines; double quotes would break the snapshot format."""
    return re.sub(r"\s+", " ", name).strip().replace('"', "'")


def build_snapshot(root: RawNode, window_title: str) -> Snapshot:
    """Build the snapshot of a window from its raw tree (`root` is the window itself)."""
    items: list[_Item] = []
    for child in root.children:
        items.extend(i for i in _convert(child, root.rect) if isinstance(i, _Item))
    items = _tidy(items, parent_name=None)
    # A region holding the whole window (e.g. a page stack) adds nothing; show its content.
    while len(items) == 1 and items[0].is_region and items[0].scroll is None:
        items = items[0].children
    elements: list[Element] = []
    _flatten(items, 0, elements, itertools.count(1))
    return Snapshot(
        window_title=window_title, elements=tuple(_with_keys(elements)), window_rect=root.rect
    )


def _with_keys(elements: list[Element]) -> list[Element]:
    """Give each numbered element a unique key: its name, plus " (2)", " (3)" if repeated."""
    seen: dict[str, int] = {}
    result = []
    for e in elements:
        if e.ref is None:
            result.append(e)
            continue
        base = e.name or e.kind
        seen[base] = seen.get(base, 0) + 1
        key = base if seen[base] == 1 else f"{base} ({seen[base]})"
        result.append(replace(e, key=key))
    return result


def _convert(node: RawNode, clip: Rect | None) -> list[_Item | _ScrollBar]:
    if node.kind in SKIPPED_KINDS or node.offscreen:
        return []
    visible = _clip(node.rect, clip)
    name = clean_name(node.name)

    if node.kind == SCROLLBAR_KIND:
        return _scrollbar(node)
    if node.kind in TEXT_KINDS:
        return [_Item(node, name, visible)] if name else []
    if node.kind in CONTROL_KINDS:
        result: list[_Item | _ScrollBar] = []
        if name or node.kind == "Edit":
            result.append(_Item(node, name, visible))
        for child in node.children:  # e.g. buttons inside a list item
            result.extend(
                i
                for i in _convert(child, _child_clip(node, visible, clip))
                if isinstance(i, _Item) and i.node.kind in CONTROL_KINDS
            )
        return result

    # Container: collect children; named containers become regions.
    collected: list[_Item | _ScrollBar] = []
    for child in node.children:
        collected.extend(_convert(child, _child_clip(node, visible, clip)))
    if not name:
        return collected
    children = [i for i in collected if isinstance(i, _Item)]
    bars = [b for b in collected if isinstance(b, _ScrollBar)]
    vertical = [b for b in bars if b.vertical]
    scroll = (vertical or bars)[0].info if bars else None
    return [_Item(node, name, visible, is_region=True, scroll=scroll, children=children)]


def _scrollbar(node: RawNode) -> list[_Item | _ScrollBar]:
    r = node.range
    if r is None or r.read_only or r.maximum <= r.minimum or not node.enabled:
        return []
    info = ScrollInfo(node.runtime_id, r.value, r.minimum, r.maximum, r.large_change)
    vertical = node.rect is None or node.rect.height >= node.rect.width
    return [_ScrollBar(info, vertical)]


def _clip(rect: Rect | None, clip: Rect | None) -> Rect | None:
    """Visible part of `rect`; `clip` None means no clipping."""
    if rect is None or clip is _HIDDEN:
        return None
    if clip is None:
        return None if rect.is_empty else rect
    return rect.intersect(clip)


def _child_clip(node: RawNode, visible: Rect | None, clip: Rect | None) -> Rect | None:
    """Clip area for the children of `node`: its own visible part, if it has a rectangle."""
    if node.rect is None:
        return clip
    return visible if visible is not None else _HIDDEN


def _tidy(items: list[_Item], parent_name: str | None) -> list[_Item]:
    """Drop duplicate texts and empty regions; merge single-region chains."""
    result: list[_Item] = []
    for item in items:
        if not item.is_region:
            if item.node.kind in TEXT_KINDS and item.name == parent_name:
                continue
            result.append(item)
            continue
        item.children = _tidy(item.children, item.name)
        while (
            len(item.children) == 1
            and item.children[0].is_region
            and _is_wrapper(item, item.children[0])
        ):
            inner = item.children[0]
            inner.scroll = item.scroll or inner.scroll
            item = inner
        if item.children:
            result.append(item)
    return result


def _is_wrapper(outer: _Item, inner: _Item) -> bool:
    """True if `outer` only wraps `inner` (e.g. a scroll area around its content).

    A list with a single row is not a wrapper: the row covers only part of the list.
    """
    a, b = outer.visible_rect, inner.visible_rect
    if a is None or b is None:
        return True
    overlap = a.intersect(b)
    return overlap is not None and overlap.width * overlap.height >= 0.8 * a.width * a.height


def _flatten(items: list[_Item], depth: int, out: list[Element], refs: Iterator[int]) -> None:
    for item in items:
        node = item.node
        if item.is_region:
            ref = next(refs) if item.scroll is not None else None
            out.append(
                Element(
                    kind=node.kind,
                    name=item.name,
                    depth=depth,
                    ref=ref,
                    rect=node.rect,
                    visible_rect=item.visible_rect,
                    runtime_id=node.runtime_id,
                    is_region=True,
                    scroll=item.scroll,
                )
            )
            _flatten(item.children, depth + 1, out, refs)
            continue
        actionable = node.kind in CONTROL_KINDS and node.enabled
        checked = node.toggle_state if Pattern.TOGGLE in node.patterns else None
        out.append(
            Element(
                kind=node.kind,
                name=item.name,
                depth=depth,
                ref=next(refs) if actionable else None,
                enabled=node.enabled,
                checked=checked,
                value=node.value if node.kind in {"Edit", "ComboBox"} else None,
                rect=node.rect,
                visible_rect=item.visible_rect,
                runtime_id=node.runtime_id,
                patterns=node.patterns,
            )
        )
