"""Done screen: order number and a 10-second countdown back to the start screen."""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer

from kiosk_app.screens.common import Screen, make_label, set_label

AUTO_RETURN_SECONDS = 10


class DoneScreen(Screen):
    def __init__(self) -> None:
        super().__init__("doneScreen", "주문 완료")
        self.remaining = AUTO_RETURN_SECONDS
        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self._tick)

        self.body.addStretch(1)
        self.message = make_label("주문이 완료되었습니다", "doneMessageLabel", role="heading")
        self.number_label = make_label("", "orderNumberLabel", role="hero")
        self.detail_label = make_label("", "doneDetailLabel")
        self.stamp_label = make_label("", "doneStampLabel")
        self.countdown_label = make_label("", "doneCountdownLabel", role="muted")
        for label in (
            self.message,
            self.number_label,
            self.detail_label,
            self.stamp_label,
            self.countdown_label,
        ):
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.body.addWidget(label)
        self.body.addStretch(2)
        self.home_button.setProperty("primary", True)

    def show_result(
        self, order_number: int, total: int, method: str, dine_in: bool, stamped: bool
    ) -> None:
        set_label(self.number_label, f"주문번호 {order_number}", f"주문번호 {order_number}번")
        place = "매장" if dine_in else "포장"
        set_label(
            self.detail_label,
            f"{method} · {total:,}원 · {place}",
            f"결제수단 {method}, 결제 금액 {total}원, {place}",
        )
        set_label(self.stamp_label, "스탬프가 적립되었습니다" if stamped else "스탬프 적립 안 함")

    def on_enter(self) -> None:
        self.remaining = AUTO_RETURN_SECONDS
        self._update_countdown()
        self.timer.start()

    def stop(self) -> None:
        self.timer.stop()

    def _tick(self) -> None:
        self.remaining -= 1
        if self.remaining <= 0:
            self.timer.stop()
            self.home_requested.emit()
        else:
            self._update_countdown()

    def _update_countdown(self) -> None:
        set_label(self.countdown_label, f"{self.remaining}초 후 처음 화면으로 돌아갑니다")
