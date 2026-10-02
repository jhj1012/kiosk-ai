"""Option selection for one menu item.

Shown as a full page inside the main window (not a separate QDialog window), so it stays
in the "Test Kiosk" UIA tree where the assistant is looking.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QGridLayout,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from kiosk_app.order import MAX_QUANTITY, MenuItem, OptionChoice, unit_price, won
from kiosk_app.screens.common import Screen, hbox, make_button, make_label, set_label

OPTION_COLUMNS = 3


def _choice_label(group_name: str, choice_name: str) -> str:
    """Prefix the group name for context, unless the choice already starts with it."""
    return choice_name if choice_name.startswith(group_name) else f"{group_name} {choice_name}"


class OptionDialog(Screen):
    added = Signal(object, tuple, int)  # MenuItem, choices, quantity
    cancelled = Signal()

    def __init__(self) -> None:
        super().__init__("optionDialog", "옵션 선택")
        self.item: MenuItem | None = None
        self.quantity = 1
        self.choice_buttons: list[tuple[OptionChoice, QPushButton]] = []
        self._button_groups: list[QButtonGroup] = []

        self.picture = make_label("", "optionItemPicture", role="art")
        self.picture.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.picture.setFixedSize(110, 110)
        self.name_label = make_label("", "optionItemName", role="heading")
        self.base_price_label = make_label("", "optionItemBasePrice")
        info = QVBoxLayout()
        info.addWidget(self.name_label)
        info.addWidget(self.base_price_label)
        top = hbox(self.picture)
        top.addLayout(info, 1)
        self.body.addLayout(top)

        self.options_host = QWidget()
        self.options_host.setObjectName("optionGroups")
        self.options_host.setAccessibleName("옵션 목록")
        self.options_layout = QVBoxLayout(self.options_host)
        self.options_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        scroll = QScrollArea()
        scroll.setObjectName("optionScroll")
        scroll.setAccessibleName("옵션 스크롤 영역")
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.options_host)
        self.body.addWidget(scroll, 1)

        self.minus_button = make_button("−", "quantityMinusButton", "수량 감소")
        self.plus_button = make_button("+", "quantityPlusButton", "수량 증가")
        self.quantity_label = make_label("", "quantityLabel", role="total")
        self.quantity_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.minus_button.clicked.connect(lambda: self._change_quantity(-1))
        self.plus_button.clicked.connect(lambda: self._change_quantity(1))
        quantity_row = hbox(
            make_label("수량", "quantityTitleLabel", role="heading"),
            self.minus_button,
            self.quantity_label,
            self.plus_button,
        )
        self.body.addLayout(quantity_row)

        self.price_label = make_label("", "optionPriceLabel", role="total")
        self.body.addWidget(self.price_label)

        cancel = make_button("취소", "optionCancelButton")
        add = make_button("담기", "optionAddButton", primary=True)
        cancel.clicked.connect(self.cancelled)
        add.clicked.connect(self._add)
        buttons = hbox(cancel, add)
        buttons.setStretch(1, 2)
        self.body.addLayout(buttons)

    def open_item(self, item: MenuItem) -> None:
        """Prepare the page for `item` with default options and quantity 1."""
        self.item = item
        self.quantity = 1
        set_label(self.picture, item.emoji or "🍽", f"{item.name} 사진")
        set_label(self.name_label, item.name, f"선택한 메뉴 {item.name}")
        set_label(self.base_price_label, f"기본 {won(item.price)}", f"기본 가격 {item.price}원")
        self._build_options(item)
        self._refresh()

    def selected_choices(self) -> tuple[OptionChoice, ...]:
        return tuple(choice for choice, button in self.choice_buttons if button.isChecked())

    def _build_options(self, item: MenuItem) -> None:
        while self.options_layout.count():
            child = self.options_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
        self.choice_buttons.clear()
        for group in self._button_groups:
            group.deleteLater()
        self._button_groups.clear()

        if not item.option_groups:
            self.options_layout.addWidget(
                make_label("선택할 옵션이 없습니다", "noOptionsLabel", role="muted")
            )
        defaults = set(item.default_choices())
        for group in item.option_groups:
            title = "선택 (여러 개 가능)" if group.multi else "선택"
            self.options_layout.addWidget(
                make_label(f"{group.name} {title}", f"optionGroup_{group.id}", role="heading")
            )
            button_group = QButtonGroup(self)
            button_group.setExclusive(not group.multi)
            self._button_groups.append(button_group)
            grid_host = QWidget()
            grid = QGridLayout(grid_host)
            grid.setContentsMargins(0, 0, 0, 0)
            for index, choice in enumerate(group.choices):
                price = f"+{won(choice.price)}" if choice.price else "+0원"
                button = make_button(
                    f"{choice.name}\n{price}",
                    f"option_{group.id}_{choice.id}",
                    f"{_choice_label(group.name, choice.name)} +{choice.price}원",
                    checkable=True,
                )
                button.setProperty("option", True)
                button.setChecked(choice in defaults)
                button.toggled.connect(self._refresh)
                button_group.addButton(button)
                self.choice_buttons.append((choice, button))
                grid.addWidget(button, index // OPTION_COLUMNS, index % OPTION_COLUMNS)
            self.options_layout.addWidget(grid_host)

    def _change_quantity(self, delta: int) -> None:
        self.quantity = max(1, min(MAX_QUANTITY, self.quantity + delta))
        self._refresh()

    def _refresh(self) -> None:
        if self.item is None:
            return
        set_label(self.quantity_label, f"{self.quantity}개", f"수량 {self.quantity}개")
        self.minus_button.setEnabled(self.quantity > 1)
        self.plus_button.setEnabled(self.quantity < MAX_QUANTITY)
        total = unit_price(self.item, self.selected_choices()) * self.quantity
        set_label(self.price_label, f"금액 {won(total)}", f"선택 금액 {total}원")

    def _add(self) -> None:
        if self.item is not None:
            self.added.emit(self.item, self.selected_choices(), self.quantity)
