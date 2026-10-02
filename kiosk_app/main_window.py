"""Main window: owns the Order and switches between screens in a QStackedWidget."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QMainWindow, QStackedWidget

from kiosk_app.order import Menu, MenuItem, OptionChoice, Order, OrderNumbers
from kiosk_app.screens.common import Screen
from kiosk_app.screens.dine_option import DineOptionScreen
from kiosk_app.screens.done import DoneScreen
from kiosk_app.screens.menu import MenuScreen
from kiosk_app.screens.option_dialog import OptionDialog
from kiosk_app.screens.payment import PaymentScreen
from kiosk_app.screens.review import ReviewScreen
from kiosk_app.screens.stamp import StampScreen
from kiosk_app.screens.start import StartScreen

WINDOW_TITLE = "Test Kiosk"  # configs/settings.yaml finds the window by this title
WINDOW_WIDTH, WINDOW_HEIGHT = 600, 900


@dataclass
class _PaidOrder:
    """What the done screen shows after the cart has been reset."""

    number: int
    total: int
    method: str
    dine_in: bool


class MainWindow(QMainWindow):
    def __init__(self, menu: Menu) -> None:
        super().__init__()
        self.setWindowTitle(WINDOW_TITLE)
        self.setObjectName("kioskMainWindow")
        self.setAccessibleName(WINDOW_TITLE)
        self.order = Order()
        self.order_numbers = OrderNumbers(start=1)
        self.paid_order: _PaidOrder | None = None

        self.start = StartScreen()
        self.dine = DineOptionScreen()
        self.menu = MenuScreen(menu, self.order)
        self.options = OptionDialog()
        self.review = ReviewScreen(self.order)
        self.payment = PaymentScreen(menu, self.order)
        self.stamp = StampScreen()
        self.done = DoneScreen()

        self.stack = QStackedWidget()
        self.stack.setObjectName("screenStack")
        self.stack.setAccessibleName("키오스크 화면")
        screens: list[Screen] = [
            self.start,
            self.dine,
            self.menu,
            self.options,
            self.review,
            self.payment,
            self.stamp,
            self.done,
        ]
        for screen in screens:
            self.stack.addWidget(screen)
            screen.home_requested.connect(self.go_home)
        self.setCentralWidget(self.stack)

        self.start.start_requested.connect(lambda: self.show_screen(self.dine))
        self.dine.chosen.connect(self._on_dine_chosen)
        self.menu.item_selected.connect(self._on_item_selected)
        self.menu.checkout_requested.connect(self._on_checkout)
        self.options.added.connect(self._on_item_added)
        self.options.cancelled.connect(lambda: self.show_screen(self.menu))
        self.review.back_requested.connect(lambda: self.show_screen(self.menu))
        self.review.confirmed.connect(self._on_dine_confirmed)
        self.payment.back_requested.connect(lambda: self.show_screen(self.review))
        self.payment.paid.connect(self._on_paid)
        self.stamp.finished.connect(self._on_stamp_finished)

        self._fit_to_screen()
        self.show_screen(self.start)

    def show_screen(self, screen: Screen) -> None:
        if screen is not self.done:
            self.done.stop()
        self.stack.setCurrentWidget(screen)
        screen.on_enter()

    def go_home(self) -> None:
        """Cancel everything and return to the start screen."""
        self.order.reset()
        self.paid_order = None
        self.menu.reset()
        self.show_screen(self.start)

    def _fit_to_screen(self) -> None:
        """Fixed 600x900, scaled down (2:3 ratio kept) if the screen is too small."""
        screen = QGuiApplication.primaryScreen()
        height = WINDOW_HEIGHT
        if screen is not None:
            height = min(WINDOW_HEIGHT, screen.availableGeometry().height() - 60)
        self.setFixedSize(height * WINDOW_WIDTH // WINDOW_HEIGHT, height)

    def _on_dine_chosen(self, dine_in: bool) -> None:
        self.order.dine_in = dine_in
        self.show_screen(self.menu)

    def _on_item_selected(self, item: MenuItem) -> None:
        self.options.open_item(item)
        self.show_screen(self.options)

    def _on_item_added(self, item: MenuItem, choices: tuple[OptionChoice, ...], qty: int) -> None:
        self.order.add(item, choices, qty)
        self.show_screen(self.menu)

    def _on_checkout(self) -> None:
        if not self.order.is_empty:
            self.show_screen(self.review)

    def _on_dine_confirmed(self, dine_in: bool) -> None:
        self.order.dine_in = dine_in
        self.show_screen(self.payment)

    def _on_paid(self) -> None:
        self.paid_order = _PaidOrder(
            number=self.order_numbers.next(),
            total=self.order.total,
            method=self.order.payment_method or "",
            dine_in=bool(self.order.dine_in),
        )
        self.show_screen(self.stamp)

    def _on_stamp_finished(self, stamped: bool) -> None:
        paid = self.paid_order
        if paid is None:
            self.go_home()
            return
        self.done.show_result(paid.number, paid.total, paid.method, paid.dine_in, stamped)
        self.order.reset()
        self.menu.reset()
        self.show_screen(self.done)
