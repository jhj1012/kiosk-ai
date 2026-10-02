"""Shared widget helpers. Every widget made here gets an objectName and an accessibleName."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

SELECTED_SUFFIX = " (선택됨)"


def make_button(
    text: str,
    object_name: str,
    accessible_name: str | None = None,
    *,
    primary: bool = False,
    checkable: bool = False,
) -> QPushButton:
    """A real QPushButton with objectName and accessibleName set.

    Checkable buttons append " (선택됨)" to their accessible name while checked, so a
    text-only reader of the UIA tree can see the selection.
    """
    button = QPushButton(text)
    button.setObjectName(object_name)
    button.setProperty("primary", primary)
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    base_name = accessible_name or text.replace("\n", " ")
    button.setAccessibleName(base_name)
    if checkable:
        button.setCheckable(True)
        button.toggled.connect(
            lambda checked: button.setAccessibleName(
                base_name + (SELECTED_SUFFIX if checked else "")
            )
        )
    return button


def make_label(
    text: str, object_name: str, accessible_name: str | None = None, *, role: str = ""
) -> QLabel:
    """A QLabel with objectName and accessibleName. `role` selects a stylesheet variant."""
    label = QLabel()
    label.setObjectName(object_name)
    label.setProperty("role", role)
    label.setWordWrap(True)
    set_label(label, text, accessible_name)
    return label


def set_label(label: QLabel, text: str, accessible_name: str | None = None) -> None:
    """Update a label's text and accessible name together."""
    label.setText(text)
    label.setAccessibleName(accessible_name or text.replace("\n", " "))


def set_status(label: QLabel, text: str, accessible_name: str | None = None) -> None:
    """Update a status message label; it is hidden while empty so the tree has no blank text."""
    set_label(label, text, accessible_name)
    label.setVisible(bool(text))


def make_list(object_name: str, accessible_name: str) -> QListWidget:
    """A read-only QListWidget."""
    widget = QListWidget()
    widget.setObjectName(object_name)
    widget.setAccessibleName(accessible_name)
    widget.setSelectionMode(QListWidget.SelectionMode.NoSelection)
    widget.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    return widget


def hbox(*widgets: QWidget, spacing: int = 8) -> QHBoxLayout:
    layout = QHBoxLayout()
    layout.setSpacing(spacing)
    for w in widgets:
        layout.addWidget(w)
    return layout


class Screen(QWidget):
    """Base class for one page of the kiosk.

    Subclasses build their content into `self.body`. Screens with `title` get a header
    with a "처음으로" button that emits `home_requested`.
    """

    home_requested = Signal()

    def __init__(self, object_name: str, title: str | None = None) -> None:
        super().__init__()
        self.setObjectName(object_name)
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 20)
        root.setSpacing(12)
        if title is not None:
            self.title_label = make_label(title, f"{object_name}Title", role="title")
            self.home_button = make_button("처음으로", f"{object_name}HomeButton")
            self.home_button.clicked.connect(self.home_requested)
            header = QHBoxLayout()
            header.addWidget(self.title_label, 1)
            header.addWidget(self.home_button)
            root.addLayout(header)
        self.body = QVBoxLayout()
        self.body.setSpacing(12)
        root.addLayout(self.body, 1)

    def on_enter(self) -> None:
        """Called every time the screen is shown. Refresh dynamic content here."""
