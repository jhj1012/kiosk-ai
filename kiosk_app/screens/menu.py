"""Menu screen: category tabs, item grid and the always-visible cart."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QGridLayout,
    QHBoxLayout,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from kiosk_app.order import CartLine, Menu, Order, won
from kiosk_app.screens.common import Screen, hbox, make_button, make_label, set_label

GRID_COLUMNS = 3


class MenuScreen(Screen):
    item_selected = Signal(object)  # MenuItem
    checkout_requested = Signal()

    def __init__(self, menu: Menu, order: Order) -> None:
        super().__init__("menuScreen", "메뉴 선택")
        self.menu = menu
        self.order = order

        # Category tabs
        self.tab_group = QButtonGroup(self)
        self.tab_buttons: dict[str, QPushButton] = {}
        tabs = QHBoxLayout()
        for category in menu.categories:
            button = make_button(
                category.name,
                f"categoryTab_{category.id}",
                f"{category.name} 카테고리",
                checkable=True,
            )
            button.setProperty("tab", True)
            button.toggled.connect(lambda checked, c=category.id: checked and self.show_category(c))
            self.tab_group.addButton(button)
            self.tab_buttons[category.id] = button
            tabs.addWidget(button)
        self.body.addLayout(tabs)

        # Item grid
        self.grid_host = QWidget()
        self.grid_host.setObjectName("menuItemGrid")
        self.grid_host.setAccessibleName("메뉴 목록")
        self.grid = QGridLayout(self.grid_host)
        self.grid.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.grid.setSpacing(8)
        scroll = QScrollArea()
        scroll.setObjectName("menuItemScroll")
        scroll.setAccessibleName("메뉴 목록 스크롤 영역")
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.grid_host)
        self.body.addWidget(scroll, 3)

        # Cart
        self.body.addWidget(make_label("장바구니", "cartTitleLabel", role="heading"))
        # Rows are plain widgets in a scroll area (not QListWidget.setItemWidget): widgets
        # embedded in list items do not show up in the UI Automation tree.
        self.cart_host = QWidget()
        self.cart_host.setObjectName("cartList")
        self.cart_host.setAccessibleName("장바구니 목록")
        self.cart_rows = QVBoxLayout(self.cart_host)
        self.cart_rows.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.cart_rows.setContentsMargins(4, 4, 4, 4)
        self.cart_rows.setSpacing(4)
        cart_scroll = QScrollArea()
        cart_scroll.setObjectName("cartScroll")
        cart_scroll.setAccessibleName("장바구니 스크롤 영역")
        cart_scroll.setProperty("cart", True)
        cart_scroll.setWidgetResizable(True)
        cart_scroll.setWidget(self.cart_host)
        self.body.addWidget(cart_scroll, 2)
        self.cart_summary = make_label("", "cartSummaryLabel", role="total")
        self.body.addWidget(self.cart_summary)
        self.clear_button = make_button("전체 삭제", "cartClearButton", "장바구니 전체 삭제")
        self.clear_button.clicked.connect(self._clear_cart)
        self.checkout_button = make_button("결제하기", "checkoutButton", primary=True)
        self.checkout_button.clicked.connect(self.checkout_requested)
        row = hbox(self.clear_button, self.checkout_button)
        row.setStretch(1, 2)
        self.body.addLayout(row)

        self.current_category = menu.categories[0].id

    def on_enter(self) -> None:
        self.show_category(self.current_category)
        self.refresh_cart()

    def reset(self) -> None:
        """Go back to the first category (used when a new order starts)."""
        self.current_category = self.menu.categories[0].id

    def show_category(self, category_id: str) -> None:
        """Fill the grid with the items of one category."""
        tab = self.tab_buttons[category_id]
        if not tab.isChecked():
            tab.setChecked(True)  # emits toggled, which calls back into show_category
            return
        self.current_category = category_id
        while self.grid.count():
            self.grid.takeAt(0).widget().deleteLater()
        for index, item in enumerate(self.menu.items_in(category_id)):
            button = make_button(
                f"{item.emoji}\n{item.name}\n{won(item.price)}",
                f"menuItem_{item.id}",
                f"{item.name} {item.price}원",
            )
            button.setProperty("menuItem", True)
            button.setMinimumHeight(110)
            button.clicked.connect(lambda _=False, i=item: self.item_selected.emit(i))
            self.grid.addWidget(button, index // GRID_COLUMNS, index % GRID_COLUMNS)

    def refresh_cart(self) -> None:
        """Rebuild the cart list and totals from the order."""
        while self.cart_rows.count():
            self.cart_rows.takeAt(0).widget().deleteLater()
        for index, line in enumerate(self.order.lines):
            self.cart_rows.addWidget(self._cart_row(index, line))
        if self.order.is_empty:
            set_label(self.cart_summary, "장바구니가 비어 있습니다", "장바구니 비어 있음")
        else:
            qty, total = self.order.total_quantity, self.order.subtotal
            set_label(
                self.cart_summary,
                f"총 수량 {qty}개   합계 {won(total)}",
                f"장바구니 총 수량 {qty}개 합계 {total}원",
            )
        self.clear_button.setEnabled(not self.order.is_empty)
        self.checkout_button.setEnabled(not self.order.is_empty)

    def _cart_row(self, index: int, line: CartLine) -> QWidget:
        desc = line.description
        row = QWidget()
        row.setObjectName(f"cartLine_{index}")
        row.setProperty("cartRow", True)
        row.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        row.setAccessibleName(f"{desc} {line.quantity}개 {line.total}원")
        text = make_label(
            f"{desc}\n{line.quantity}개 · {won(line.total)}",
            f"cartLineLabel_{index}",
            f"{desc} {line.quantity}개 {line.total}원",
        )
        minus = make_button("−", f"cartLineMinus_{index}", f"{desc} 수량 감소")
        plus = make_button("+", f"cartLinePlus_{index}", f"{desc} 수량 증가")
        remove = make_button("삭제", f"cartLineRemove_{index}", f"{desc} 삭제")
        minus.clicked.connect(lambda: self._change(index, -1))
        plus.clicked.connect(lambda: self._change(index, 1))
        remove.clicked.connect(lambda: self._remove(index))
        for button in (minus, plus, remove):
            button.setProperty("small", True)
        layout = QHBoxLayout(row)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.addWidget(text, 1)
        for button in (minus, plus, remove):
            layout.addWidget(button)
        return row

    def _change(self, index: int, delta: int) -> None:
        self.order.change_quantity(index, delta)
        self.refresh_cart()

    def _remove(self, index: int) -> None:
        self.order.remove(index)
        self.refresh_cart()

    def _clear_cart(self) -> None:
        self.order.clear()
        self.refresh_cart()
