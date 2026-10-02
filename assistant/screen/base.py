"""The interface between the agent and a screen backend.

`uia.py` implements it for Windows UI Automation; tests use a fake. All actions should work
through UIA patterns (no mouse), so they keep working while an overlay covers the window.
"""

from __future__ import annotations

from typing import Literal, Protocol

from assistant.screen.model import Element, Snapshot

ScrollDirection = Literal["up", "down"]


class ScreenError(Exception):
    """The target window cannot be read."""


class WindowNotFoundError(ScreenError):
    """The target window does not exist or is hidden (e.g. on another virtual desktop)."""


class ActionError(ScreenError):
    """An action could not be performed on an element."""


class Screen(Protocol):
    def read(self) -> Snapshot:
        """Read the target window now."""
        ...

    def invoke(self, element: Element) -> None:
        """Press a button (Invoke pattern)."""
        ...

    def toggle(self, element: Element) -> None:
        """Flip a check box or checkable button (Toggle pattern)."""
        ...

    def select(self, element: Element) -> None:
        """Select a list item, radio button or tab (SelectionItem pattern)."""
        ...

    def set_value(self, element: Element, text: str) -> None:
        """Replace the text of an editable field (Value pattern)."""
        ...

    def scroll(self, region: Element, direction: ScrollDirection) -> None:
        """Scroll a region by about one page (its scroll bar's RangeValue pattern)."""
        ...

    def click(self, element: Element) -> None:
        """Mouse click in the middle of the element. Last resort: needs the window uncovered."""
        ...
