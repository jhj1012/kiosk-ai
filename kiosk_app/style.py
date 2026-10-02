"""Application stylesheet (light café theme)."""

STYLESHEET = """
QWidget { background: #faf7f0; color: #3b2f2a; font-size: 15px; }
QLabel[role="hero"] { font-size: 44px; font-weight: bold; color: #6b4226; }
QLabel[role="art"] { font-size: 72px; background: #f1e7d6; border-radius: 16px; }
QLabel[role="title"] { font-size: 20px; font-weight: bold; }
QLabel[role="heading"] { font-size: 17px; font-weight: bold; }
QLabel[role="total"] { font-size: 18px; font-weight: bold; color: #6b4226; }
QLabel[role="notice"] { color: #c0392b; font-weight: bold; }
QLabel[role="muted"] { color: #8a7d74; }
QLabel[role="phone"] { font-size: 30px; font-weight: bold; padding: 8px;
    border: 2px solid #d9cbb5; border-radius: 10px; background: white; }

QPushButton { background: white; border: 2px solid #d9cbb5; border-radius: 12px;
    padding: 10px 14px; font-size: 16px; }
QPushButton:hover { border-color: #b08960; }
QPushButton:pressed { background: #f1e7d6; }
QPushButton:disabled { color: #b5aba3; border-color: #ece4d8; }
QPushButton:checked { background: #6b4226; color: white; border-color: #6b4226; }
QPushButton[primary="true"] { background: #6b4226; color: white; border-color: #6b4226;
    font-size: 18px; font-weight: bold; }
QPushButton[primary="true"]:disabled { background: #cfc3b8; border-color: #cfc3b8; }
QPushButton[tab="true"] { font-weight: bold; }
QPushButton[menuItem="true"] { font-size: 15px; }
QPushButton[small="true"] { padding: 4px 10px; min-width: 30px; }
QPushButton[keypad="true"] { font-size: 22px; }

QListWidget { background: white; border: 2px solid #d9cbb5; border-radius: 10px; }
QListWidget::item { border-bottom: 1px solid #efe7da; padding: 4px; }
QScrollArea { border: none; }
QScrollBar:vertical { width: 10px; background: transparent; margin: 2px; }
QScrollBar::handle:vertical { background: #d9cbb5; border-radius: 4px; min-height: 30px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: none; }
QScrollArea[cart="true"] { background: white; border: 2px solid #d9cbb5; border-radius: 10px; }
QScrollArea[cart="true"] > QWidget > QWidget { background: white; }
QWidget[cartRow="true"] { background: #fbf8f3; border-radius: 8px; }
QWidget[cartRow="true"] QLabel { background: transparent; }
"""
