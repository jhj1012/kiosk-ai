"""Stamp saving: enter a phone number on an on-screen keypad, or skip."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QGridLayout

from kiosk_app.order import format_phone, is_valid_phone
from kiosk_app.screens.common import Screen, hbox, make_button, make_label, set_label, set_status

MAX_DIGITS = 11
KEYPAD = ("1", "2", "3", "4", "5", "6", "7", "8", "9", "지우기", "0", "모두 지우기")


class StampScreen(Screen):
    finished = Signal(bool)  # True = stamp saved

    def __init__(self) -> None:
        super().__init__("stampScreen", "스탬프 적립")
        self.digits = ""
        self.body.addWidget(
            make_label(
                "결제가 완료되었습니다.\n스탬프를 적립하려면 휴대폰 번호를 입력해주세요",
                "stampGuideLabel",
            )
        )
        self.phone_label = make_label("", "stampPhoneLabel", role="phone")
        self.phone_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.body.addWidget(self.phone_label)
        self.status_label = make_label("", "stampStatusLabel", role="notice")
        self.body.addWidget(self.status_label)

        keypad = QGridLayout()
        for index, key in enumerate(KEYPAD):
            if key.isdigit():
                button = make_button(key, f"keypad_{key}", f"숫자 {key}")
                button.clicked.connect(lambda _=False, k=key: self._press(k))
            elif key == "지우기":
                button = make_button(key, "keypadBackspace", "한 글자 지우기")
                button.clicked.connect(lambda: self._set_digits(self.digits[:-1]))
            else:
                button = make_button(key, "keypadClear", "번호 모두 지우기")
                button.clicked.connect(lambda: self._set_digits(""))
            button.setProperty("keypad", True)
            button.setMinimumHeight(72)
            keypad.addWidget(button, index // 3, index % 3)
        self.body.addLayout(keypad, 1)

        skip = make_button("건너뛰기", "stampSkipButton", "적립 건너뛰기")
        save = make_button("적립하기", "stampSaveButton", "스탬프 적립하기", primary=True)
        skip.clicked.connect(lambda: self.finished.emit(False))
        save.clicked.connect(self._save)
        row = hbox(skip, save)
        row.setStretch(1, 2)
        self.body.addLayout(row)

    def on_enter(self) -> None:
        set_status(self.status_label, "")
        self._set_digits("")

    def _press(self, key: str) -> None:
        if len(self.digits) < MAX_DIGITS:
            self._set_digits(self.digits + key)

    def _set_digits(self, digits: str) -> None:
        self.digits = digits
        if digits:
            set_label(
                self.phone_label, format_phone(digits), f"입력한 전화번호 {format_phone(digits)}"
            )
        else:
            set_label(self.phone_label, "010-0000-0000", "입력한 전화번호 없음")

    def _save(self) -> None:
        if is_valid_phone(self.digits):
            self.finished.emit(True)
        else:
            set_status(self.status_label, "올바른 휴대폰 번호를 입력해주세요")
