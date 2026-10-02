"""Dine-in or take-out choice ("먹고 갈게요" / "갖고 갈게요")."""

from PySide6.QtCore import Qt, Signal

from kiosk_app.screens.common import Screen, make_button, make_label


class DineOptionScreen(Screen):
    chosen = Signal(bool)  # True = dine in

    def __init__(self) -> None:
        super().__init__("dineOptionScreen", "식사 방법 선택")
        question = make_label("어디에서 드시나요?", "dineQuestionLabel", role="heading")
        question.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.body.addStretch(1)
        self.body.addWidget(question)
        for text, name, dine_in in (
            ("먹고 갈게요", "dineInButton", True),
            ("갖고 갈게요", "takeOutButton", False),
        ):
            button = make_button(text, name, primary=True)
            button.setMinimumHeight(120)
            button.clicked.connect(lambda _=False, d=dine_in: self.chosen.emit(d))
            self.body.addWidget(button)
        self.body.addStretch(2)
