"""Screen snapshot data: what the assistant knows about the target window at one moment.

Plain Python with no Windows imports, so it can be used in tests and by the future overlay.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


@dataclass(frozen=True)
class Rect:
    """Screen rectangle in physical pixels."""

    left: int
    top: int
    right: int
    bottom: int

    @property
    def width(self) -> int:
        return max(0, self.right - self.left)

    @property
    def height(self) -> int:
        return max(0, self.bottom - self.top)

    @property
    def is_empty(self) -> bool:
        return self.width == 0 or self.height == 0

    @property
    def center(self) -> tuple[int, int]:
        return (self.left + self.right) // 2, (self.top + self.bottom) // 2

    def intersect(self, other: Rect) -> Rect | None:
        """The overlapping part, or None if the rectangles do not overlap."""
        rect = Rect(
            max(self.left, other.left),
            max(self.top, other.top),
            min(self.right, other.right),
            min(self.bottom, other.bottom),
        )
        return None if rect.is_empty else rect


class Pattern(StrEnum):
    """UI Automation control patterns the assistant can use to act without the mouse."""

    INVOKE = "invoke"  # press a button
    TOGGLE = "toggle"  # check boxes and checkable buttons
    SELECT = "select"  # SelectionItem: list items, radio buttons, tabs
    VALUE = "value"  # editable text
    RANGE = "range"  # RangeValue: scroll bars, sliders


@dataclass(frozen=True)
class ScrollInfo:
    """A scroll bar that scrolls a region, read from its RangeValue pattern."""

    runtime_id: tuple[int, ...]
    value: float
    minimum: float
    maximum: float
    large_change: float

    @property
    def more_above(self) -> bool:
        return self.value > self.minimum + 0.5

    @property
    def more_below(self) -> bool:
        return self.value < self.maximum - 0.5


@dataclass(frozen=True)
class Element:
    """One line of the snapshot: a control, a text, or a named region (group heading).

    `ref` is the number the LLM uses to act on the element. It is only valid for the snapshot
    it came from. Elements without a ref (texts, disabled controls) are shown for context.
    """

    kind: str  # UIA control type, e.g. "Button", "CheckBox", "Text", "Group"
    name: str
    depth: int = 0  # nesting level under named regions, for display
    ref: int | None = None
    enabled: bool = True
    checked: bool | None = None  # toggle state; None if the element cannot be toggled
    value: str | None = None  # text of an editable field
    rect: Rect | None = None  # bounding rectangle on screen
    visible_rect: Rect | None = None  # part not clipped by scroll areas; None = scrolled away
    runtime_id: tuple[int, ...] = ()  # UIA RuntimeId: finds the same element in a later read
    patterns: frozenset[Pattern] = frozenset()
    is_region: bool = False  # a named container, shown as <name>
    scroll: ScrollInfo | None = None  # set on regions that can be scrolled
    key: str = ""  # unique name the LLM uses to act on a numbered element ("이름 (2)" if repeated)

    @property
    def label(self) -> str:
        """Short description for logs and action results, e.g. 'Button "담기"'."""
        if self.is_region:
            return f"<{self.name}>"
        return f'{self.kind} "{self.name}"'

    @property
    def is_toggleable(self) -> bool:
        return Pattern.TOGGLE in self.patterns and self.checked is not None


@dataclass(frozen=True)
class Snapshot:
    """Everything visible in the target window at one moment."""

    window_title: str
    elements: tuple[Element, ...]
    window_rect: Rect | None = None

    def by_ref(self, ref: int) -> Element | None:
        return next((e for e in self.elements if e.ref == ref), None)

    def by_key(self, key: str) -> Element | None:
        return next((e for e in self.elements if e.ref is not None and e.key == key), None)

    @property
    def keys(self) -> list[str]:
        return [e.key for e in self.elements if e.ref is not None]

    def find(self, runtime_id: tuple[int, ...]) -> Element | None:
        """The element with this UIA RuntimeId, if it is still on screen."""
        if not runtime_id:
            return None
        return next((e for e in self.elements if e.runtime_id == runtime_id), None)

    @property
    def refs(self) -> list[int]:
        return [e.ref for e in self.elements if e.ref is not None]

    @property
    def scroll_refs(self) -> list[int]:
        return [e.ref for e in self.elements if e.ref is not None and e.scroll is not None]

    @property
    def busy(self) -> bool:
        """True if no control can be used, e.g. while the kiosk processes a payment."""
        return not any(e.ref is not None and not e.is_region for e in self.elements)

    def controls(self) -> frozenset[tuple[int, ...] | tuple[str, str]]:
        """Identity of every control, enabled or not, ignoring state: changes only when
        controls appear or disappear (new page, other tab), not when one is toggled."""
        return frozenset(
            e.runtime_id or (e.kind, e.name)
            for e in self.elements
            if not e.is_region and (e.ref is not None or not e.enabled)
        )

    def signature(self) -> tuple[object, ...]:
        """What must stay the same between two reads for the screen to count as settled."""
        return tuple(
            (e.kind, e.name, e.enabled, e.checked, e.value, e.scroll and e.scroll.value)
            for e in self.elements
        )
