"""Run the test kiosk: `uv run python -m kiosk_app`."""

import sys

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication

from kiosk_app.main_window import MainWindow
from kiosk_app.menu_data import load_menu
from kiosk_app.style import STYLESHEET


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Test Kiosk")
    app.setFont(QFont("Malgun Gothic", 11))
    app.setStyleSheet(STYLESHEET)
    window = MainWindow(load_menu())
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
