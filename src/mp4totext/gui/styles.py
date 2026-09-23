STYLESHEET = """
QWidget {
    background: #f4f6f3;
    color: #17221b;
    font-family: "Yu Gothic UI";
    font-size: 12px;
}
QLabel#title { font-family: "Bahnschrift"; font-size: 22px; font-weight: 700; }
QLabel#subtitle { color: #526258; }
QLabel#activeFile { font-size: 13px; font-weight: 600; color: #19633d; }
QLabel#modelStatus { color: #526258; }
QGroupBox {
    border: 1px solid #aab6ae;
    border-radius: 6px;
    margin-top: 2px;
}
QListWidget#fileList {
    background: #ffffff;
    border: 2px dashed #7c9183;
    border-radius: 6px;
}
QListWidget#fileList::item { padding: 0px 4px; margin: 0px; }
QPushButton, QLineEdit, QComboBox {
    min-height: 24px;
    border: 1px solid #aab6ae;
    border-radius: 4px;
    background: #ffffff;
    padding: 0 10px;
}
QPushButton:hover { border-color: #276b49; }
QPushButton#compactButton, QPushButton#languageButton {
    min-height: 16px;
    font-size: 10px;
    padding: 0 6px;
}
QPushButton#languageButton:checked {
    background: #19633d;
    color: #ffffff;
    border-color: #19633d;
    font-weight: 600;
}
QPushButton[danger="true"] { background: #f6d9d6; border-color: #d98b83; color: #7a2b23; }
QPushButton[danger="true"]:hover { background: #f0c4bf; border-color: #a33a32; }
QPushButton[danger="true"]:disabled { background: #dce2de; color: #7b8780; border-color: #aab6ae; }
QPushButton#primaryButton { background: #19633d; color: #ffffff; border: none; font-weight: 600; }
QPushButton#primaryButton:hover { background: #124d2f; }
QPushButton#cancelButton:enabled {
    background: #a33a32;
    color: #ffffff;
    border: none;
    font-weight: 600;
}
QPushButton#cancelButton:enabled:hover { background: #842d27; }
QPushButton:disabled { background: #dce2de; color: #7b8780; }
QLineEdit:disabled, QComboBox:disabled { background: #e8ebe7; color: #9aa39c; }
QRadioButton { spacing: 6px; background: transparent; }
QRadioButton::indicator {
    width: 14px;
    height: 14px;
    border: 1px solid #7c9183;
    border-radius: 7px;
    background: #ffffff;
}
QRadioButton::indicator:checked { background: #19633d; border: 1px solid #19633d; }
QRadioButton::indicator:disabled { background: #dce2de; border-color: #aab6ae; }
QRadioButton::indicator:checked:disabled { background: #6f9c82; border-color: #6f9c82; }
"""
