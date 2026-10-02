"""Order review: "주문 세부내역을 다시 확인해주세요" with dine-in / take-out confirmation."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QListWidget, QListWidgetItem

from kiosk_app.order import Order, won
from kiosk_app.screens.common import Screen, hbox, make_button, make_label, make_list, set_label


def fill_order_list(widget: QListWidget, order: Order) -> None:
    """Show one numbered row per cart line, e.g. "1. 아메리카노 (ICE)  2개  9,000원"."""
    widget.clear()
    for number, line in enumerate(order.lines, start=1):
        item = QListWidgetItem(
            f"{number}. {line.description}   {line.quantity}개   {won(line.total)}"
        )
        item.setData(
            Qt.ItemDataRole.AccessibleTextRole,
            f"{number}번 {line.description} {line.quantity}개 {line.total}원",
        )
        widget.addItem(item)


class ReviewScreen(Screen):
    back_requested = Signal()
    confirmed = Signal(bool)  # True = dine in (다회용컵)

    def __init__(self, order: Order) -> None:
        super().__init__("reviewScreen", "주문 세부내역을 다시 확인해주세요")
        self.order = order
        self.order_list = make_list("reviewOrderList", "주문 세부내역 목록")
        self.body.addWidget(self.order_list, 1)
        self.body.addWidget(
            make_label("* 매장 이용시 일회용컵 사용불가", "disposableCupNoticeLabel", role="notice")
        )
        self.summary = make_label("", "reviewSummaryLabel", role="total")
        self.body.addWidget(self.summary)
        self.dine_label = make_label("", "reviewDineChoiceLabel", role="muted")
        self.body.addWidget(self.dine_label)

        back = make_button("←", "reviewBackButton", "이전 화면으로")
        back.setProperty("small", True)
        back.clicked.connect(self.back_requested)
        self.dine_in_button = make_button(
            "먹고가기\n(다회용컵)", "reviewDineInButton", primary=True
        )
        self.take_out_button = make_button(
            "포장하기\n(일회용컵)", "reviewTakeOutButton", primary=True
        )
        self.dine_in_button.clicked.connect(lambda: self.confirmed.emit(True))
        self.take_out_button.clicked.connect(lambda: self.confirmed.emit(False))
        for button in (self.dine_in_button, self.take_out_button):
            button.setMinimumHeight(90)
        row = hbox(back, self.dine_in_button, self.take_out_button)
        row.setStretch(1, 2)
        row.setStretch(2, 2)
        self.body.addLayout(row)

    def on_enter(self) -> None:
        fill_order_list(self.order_list, self.order)
        qty, total = self.order.total_quantity, self.order.subtotal
        set_label(
            self.summary,
            f"총 수량 {qty}개   총 결제금액 {won(total)}",
            f"총 수량 {qty}개 총 결제금액 {total}원",
        )
        choice = {True: "먹고 갈게요", False: "갖고 갈게요", None: "선택 안 함"}[self.order.dine_in]
        set_label(self.dine_label, f"처음에 선택한 식사 방법: {choice}")
