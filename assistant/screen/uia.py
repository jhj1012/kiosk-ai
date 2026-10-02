"""Windows UI Automation backend: read the target window and act through UIA patterns.

This is the only module that imports pywinauto / comtypes, and it does so lazily, so the rest
of the assistant (and the tests) run anywhere.

Threading: COM objects belong to the thread that created them. Create `UiaScreen` anywhere,
but call `attach()`, `read()` and the actions only from the one thread that runs the agent
(not the Qt main thread later).
"""

from __future__ import annotations

import contextlib
import logging
import threading
import warnings
from typing import Any

from assistant.config import ScreenConfig
from assistant.screen.base import ActionError, ScrollDirection, WindowNotFoundError
from assistant.screen.model import Element, Pattern, Rect, Snapshot
from assistant.screen.reader import RangeInfo, RawNode, build_snapshot

log = logging.getLogger(__name__)

# pywinauto pattern names (see pywinauto.uia_defines.pattern_ids)
_PATTERN_NAMES = {
    Pattern.INVOKE: "Invoke",
    Pattern.TOGGLE: "Toggle",
    Pattern.SELECT: "SelectionItem",
    Pattern.VALUE: "Value",
    Pattern.RANGE: "RangeValue",
}
_TOGGLE_ON = 1  # ToggleState_On


class UiaScreen:
    def __init__(self, config: ScreenConfig) -> None:
        self.title = config.window_title
        self._thread: int | None = None
        self._uia: Any = None  # pywinauto IUIA singleton
        self._cache_request: Any = None
        self._window: Any = None
        self._live: dict[tuple[int, ...], Any] = {}  # RuntimeId -> IUIAutomationElement

    # ----- setup -----

    def attach(self) -> None:
        """Find the target window. Raises WindowNotFoundError with a hint if it is missing."""
        self._init_com()
        self._window = self._find_window()
        log.info("attached to window %r", self.title)

    def _init_com(self) -> None:
        if self._thread is not None:
            self._check_thread()
            return
        import comtypes

        with contextlib.suppress(OSError):  # OSError: already initialized in this thread
            comtypes.CoInitializeEx(comtypes.COINIT_MULTITHREADED)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")  # pywinauto has old invalid escape sequences
            from pywinauto.uia_defines import IUIA
        self._uia = IUIA()
        self._cache_request = self._make_cache_request()
        self._thread = threading.get_ident()

    def _check_thread(self) -> None:
        if self._thread != threading.get_ident():
            raise RuntimeError("UiaScreen must be used from the thread that attached it")

    def _make_cache_request(self) -> Any:
        dll = self._uia.UIA_dll
        request = self._uia.iuia.CreateCacheRequest()
        for prop in _cached_properties(dll):
            request.AddProperty(prop)
        request.TreeScope = dll.TreeScope_Subtree
        request.TreeFilter = self._uia.iuia.RawViewCondition
        return request

    def _find_window(self) -> Any:
        dll = self._uia.UIA_dll
        iuia = self._uia.iuia
        window_type = dll.UIA_WindowControlTypeId
        condition = iuia.CreateAndCondition(
            iuia.CreatePropertyCondition(dll.UIA_NamePropertyId, self.title),
            iuia.CreatePropertyCondition(dll.UIA_ControlTypePropertyId, window_type),
        )
        window = self._uia.root.FindFirst(dll.TreeScope_Children, condition)
        if not window:
            raise WindowNotFoundError(
                f'Window "{self.title}" was not found. Start the kiosk first. If it is running, '
                "move it to the current virtual desktop: windows on other desktops are hidden "
                "from UI Automation."
            )
        return window

    # ----- reading -----

    def read(self) -> Snapshot:
        import comtypes

        self._check_thread()
        if self._window is None:
            self.attach()
        try:
            cached = self._window.BuildUpdatedCache(self._cache_request)
        except comtypes.COMError:
            log.info("window handle is stale, attaching again")
            self.attach()
            try:
                cached = self._window.BuildUpdatedCache(self._cache_request)
            except comtypes.COMError as e:
                raise WindowNotFoundError(f'Window "{self.title}" cannot be read: {e}') from e
        live: dict[tuple[int, ...], Any] = {}
        root = self._raw_node(cached, live)
        self._live = live
        return build_snapshot(root, self.title)

    def _raw_node(self, element: Any, live: dict[tuple[int, ...], Any]) -> RawNode:
        dll = self._uia.UIA_dll

        def prop(pid: int) -> Any:
            return element.GetCachedPropertyValue(pid)

        runtime_id = tuple(prop(dll.UIA_RuntimeIdPropertyId) or ())
        if runtime_id:
            live[runtime_id] = element
        patterns = frozenset(
            pattern
            for pattern, pid in (
                (Pattern.INVOKE, dll.UIA_IsInvokePatternAvailablePropertyId),
                (Pattern.TOGGLE, dll.UIA_IsTogglePatternAvailablePropertyId),
                (Pattern.SELECT, dll.UIA_IsSelectionItemPatternAvailablePropertyId),
                (Pattern.VALUE, dll.UIA_IsValuePatternAvailablePropertyId),
                (Pattern.RANGE, dll.UIA_IsRangeValuePatternAvailablePropertyId),
            )
            if prop(pid) is True
        )
        toggle_state = None
        if Pattern.TOGGLE in patterns:
            toggle_state = prop(dll.UIA_ToggleToggleStatePropertyId) == _TOGGLE_ON
        value = None
        if Pattern.VALUE in patterns:
            raw_value = prop(dll.UIA_ValueValuePropertyId)
            value = raw_value if isinstance(raw_value, str) else None
        range_info = None
        if Pattern.RANGE in patterns:
            range_info = RangeInfo(
                value=_number(prop(dll.UIA_RangeValueValuePropertyId)),
                minimum=_number(prop(dll.UIA_RangeValueMinimumPropertyId)),
                maximum=_number(prop(dll.UIA_RangeValueMaximumPropertyId)),
                large_change=_number(prop(dll.UIA_RangeValueLargeChangePropertyId)),
                read_only=prop(dll.UIA_RangeValueIsReadOnlyPropertyId) is True,
            )
        node = RawNode(
            kind=self._uia.known_control_type_ids.get(prop(dll.UIA_ControlTypePropertyId), "?"),
            name=prop(dll.UIA_NamePropertyId) or "",
            enabled=prop(dll.UIA_IsEnabledPropertyId) is True,
            offscreen=prop(dll.UIA_IsOffscreenPropertyId) is True,
            rect=_rect(prop(dll.UIA_BoundingRectanglePropertyId)),
            runtime_id=runtime_id,
            patterns=patterns,
            toggle_state=toggle_state,
            value=value,
            range=range_info,
        )
        children = element.GetCachedChildren()
        if children:
            for i in range(children.Length):
                node.children.append(self._raw_node(children.GetElement(i), live))
        return node

    # ----- actions -----

    def invoke(self, element: Element) -> None:
        self._pattern(element, Pattern.INVOKE).Invoke()

    def toggle(self, element: Element) -> None:
        self._pattern(element, Pattern.TOGGLE).Toggle()

    def select(self, element: Element) -> None:
        self._pattern(element, Pattern.SELECT).Select()

    def set_value(self, element: Element, text: str) -> None:
        self._pattern(element, Pattern.VALUE).SetValue(text)

    def scroll(self, region: Element, direction: ScrollDirection) -> None:
        info = region.scroll
        if info is None:
            raise ActionError(f"{region.label} cannot be scrolled")
        bar = self._live_element(info.runtime_id, region.label)
        # Some toolkits report a tiny LargeChange (Qt: 20 px), so move at least a quarter.
        step = max(info.large_change, (info.maximum - info.minimum) / 4)
        target = info.value + (step if direction == "down" else -step)
        target = min(info.maximum, max(info.minimum, target))
        self._query(bar, Pattern.RANGE, region.label).SetValue(target)

    def click(self, element: Element) -> None:
        rect = element.visible_rect
        if rect is None:
            raise ActionError(f"{element.label} is not visible, so it cannot be clicked")
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            from pywinauto import mouse
        log.warning("mouse fallback: clicking %s at %s", element.label, rect.center)
        mouse.click(coords=rect.center)

    def _pattern(self, element: Element, pattern: Pattern) -> Any:
        live = self._live_element(element.runtime_id, element.label)
        return self._query(live, pattern, element.label)

    def _live_element(self, runtime_id: tuple[int, ...], label: str) -> Any:
        self._check_thread()
        live = self._live.get(runtime_id)
        if live is None:
            raise ActionError(f"{label} is no longer on the screen")
        return live

    def _query(self, live: Any, pattern: Pattern, label: str) -> Any:
        import comtypes

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            from pywinauto.uia_defines import NoPatternInterfaceError, get_elem_interface
        try:
            return get_elem_interface(live, _PATTERN_NAMES[pattern])
        except NoPatternInterfaceError as e:
            raise ActionError(f"{label} does not support {pattern.value}") from e
        except comtypes.COMError as e:
            raise ActionError(f"{label} is no longer on the screen") from e


def _cached_properties(dll: Any) -> list[int]:
    names = [
        "Name",
        "ControlType",
        "IsEnabled",
        "IsOffscreen",
        "BoundingRectangle",
        "RuntimeId",
        "IsInvokePatternAvailable",
        "IsTogglePatternAvailable",
        "IsSelectionItemPatternAvailable",
        "IsValuePatternAvailable",
        "IsRangeValuePatternAvailable",
        "ToggleToggleState",
        "ValueValue",
        "RangeValueValue",
        "RangeValueMinimum",
        "RangeValueMaximum",
        "RangeValueLargeChange",
        "RangeValueIsReadOnly",
    ]
    return [getattr(dll, f"UIA_{name}PropertyId") for name in names]


def _rect(value: Any) -> Rect | None:
    """UIA BoundingRectangle is (left, top, width, height)."""
    try:
        left, top, width, height = (int(v) for v in value)
    except (TypeError, ValueError):
        return None
    if width <= 0 or height <= 0:
        return None
    return Rect(left, top, left + width, top + height)


def _number(value: Any) -> float:
    return float(value) if isinstance(value, int | float) else 0.0
