"""Start screen: store name, picture and the "주문하기" button."""

from PySide6.QtCore import Qt, Signal

from kiosk_app.screens.common import Screen, make_button, make_label


class StartScreen(Screen):
    start_requested = Signal()

    def __init__(self) -> None:
        super().__init__("startScreen")
        self.body.addStretch(1)
        store = make_label("트레비앙", "storeNameLabel", role="hero")
        art = make_label("🥤 ☕", "storeArtLabel", "트레비앙 음료 그림", role="art")
        hint = make_label("버튼을 눌러 주문을 시작하세요", "startHintLabel")
        for label in (store, art, hint):
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.body.addWidget(label)
        self.body.addStretch(1)
        self.order_button = make_button("주문하기", "startOrderButton", primary=True)
        self.order_button.setMinimumHeight(90)
        self.order_button.clicked.connect(self.start_requested)
        self.body.addWidget(self.order_button)
