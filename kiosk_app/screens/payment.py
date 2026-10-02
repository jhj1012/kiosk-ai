"""Payment screen: summary, discounts, payment method and a fake 2-second payment."""

from __future__ import annotations

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import QButtonGroup, QGridLayout, QPushButton

from kiosk_app.order import Discount, Menu, Order, won
from kiosk_app.screens.common import (
    Screen,
    hbox,
    make_button,
    make_label,
    make_list,
    set_label,
    set_status,
)
from kiosk_app.screens.review import fill_order_list

PAYMENT_METHODS = (
    ("card", "카드"),
    ("mobile", "모바일 결제"),
    ("easy_pay", "간편결제"),
    ("gift_card", "모바일상품권"),
)
FAKE_PAYMENT_MS = 2000


class PaymentScreen(Screen):
    back_requested = Signal()
    paid = Signal()

    def __init__(self, menu: Menu, order: Order) -> None:
        super().__init__("paymentScreen", "결제")
        self.order = order
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self._finish_payment)

        self.body.addWidget(make_label("주문 내역", "paymentSummaryTitle", role="heading"))
        self.order_list = make_list("paymentOrderList", "결제할 주문 내역 목록")
        self.body.addWidget(self.order_list, 1)

        self.body.addWidget(make_label("할인수단", "discountTitleLabel", role="heading"))
        self.discounts = menu.discounts
        self.discount_buttons: list[QPushButton] = []
        discount_row = hbox()
        for discount in menu.discounts:
            button = make_button(
                f"{discount.name}\n-{won(discount.amount)}",
                f"discount_{discount.id}",
                f"할인 {discount.name} {discount.amount}원",
                checkable=True,
            )
            button.setProperty("option", True)
            button.toggled.connect(lambda checked, d=discount: self._toggle_discount(d, checked))
            self.discount_buttons.append(button)
            discount_row.addWidget(button)
        self.body.addLayout(discount_row)

        self.body.addWidget(make_label("결제수단", "paymentMethodTitleLabel", role="heading"))
        self.method_group = QButtonGroup(self)
        self.method_buttons: dict[str, QPushButton] = {}
        methods = QGridLayout()
        for index, (method_id, name) in enumerate(PAYMENT_METHODS):
            button = make_button(
                name, f"paymentMethod_{method_id}", f"결제수단 {name}", checkable=True
            )
            button.setProperty("option", True)
            button.setMinimumHeight(64)
            button.toggled.connect(lambda checked, n=name: checked and self._choose_method(n))
            self.method_group.addButton(button)
            self.method_buttons[name] = button
            methods.addWidget(button, index // 2, index % 2)
        self.body.addLayout(methods)

        self.subtotal_label = make_label("", "paymentSubtotalLabel")
        self.discount_label = make_label("", "paymentDiscountLabel")
        self.total_label = make_label("", "paymentTotalLabel", role="total")
        self.status_label = make_label("", "paymentStatusLabel", role="notice")
        for label in (
            self.subtotal_label,
            self.discount_label,
            self.total_label,
            self.status_label,
        ):
            self.body.addWidget(label)

        self.back_button = make_button("이전", "paymentBackButton", "이전 화면으로 돌아가기")
        self.pay_button = make_button("결제", "payButton", "결제", primary=True)
        self.back_button.clicked.connect(self.back_requested)
        self.pay_button.clicked.connect(self._start_payment)
        row = hbox(self.back_button, self.pay_button)
        row.setStretch(1, 2)
        self.body.addLayout(row)
        self.busy_widgets = [
            *self.discount_buttons,
            *self.method_buttons.values(),
            self.back_button,
            self.pay_button,
            self.home_button,
        ]

    def on_enter(self) -> None:
        fill_order_list(self.order_list, self.order)
        for button, discount in zip(self.discount_buttons, self.discounts, strict=True):
            button.setChecked(discount in self.order.discounts)
        self._sync_method_buttons()
        self._set_busy(False)
        set_status(self.status_label, "")
        self._refresh()

    def _toggle_discount(self, discount: Discount, enabled: bool) -> None:
        self.order.set_discount(discount, enabled)
        self._refresh()

    def _choose_method(self, name: str) -> None:
        self.order.payment_method = name
        set_status(self.status_label, f"{name}(으)로 결제합니다. 결제 버튼을 눌러주세요")

    def _sync_method_buttons(self) -> None:
        self.method_group.setExclusive(False)
        for name, button in self.method_buttons.items():
            button.setChecked(name == self.order.payment_method)
        self.method_group.setExclusive(True)

    def _refresh(self) -> None:
        o = self.order
        set_label(self.subtotal_label, f"주문 금액 {won(o.subtotal)}", f"주문 금액 {o.subtotal}원")
        set_label(
            self.discount_label,
            f"할인 금액 -{won(o.discount_total)}",
            f"할인 금액 {o.discount_total}원",
        )
        set_label(self.total_label, f"결제할 금액 {won(o.total)}", f"결제할 금액 {o.total}원")

    def _start_payment(self) -> None:
        if self.order.payment_method is None:
            set_status(self.status_label, "결제수단을 선택해주세요")
            return
        self._set_busy(True)
        set_status(self.status_label, "결제 중...", "결제 중입니다")
        self.timer.start(FAKE_PAYMENT_MS)

    def _finish_payment(self) -> None:
        set_status(self.status_label, "결제가 완료되었습니다")
        self._set_busy(False)
        self.paid.emit()

    def _set_busy(self, busy: bool) -> None:
        for widget in self.busy_widgets:
            widget.setEnabled(not busy)
