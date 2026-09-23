from string import Formatter

import pytest
from PySide6.QtCore import QCoreApplication
from pytestqt.qtbot import QtBot

from mp4totext.gui.i18n import _STRINGS, Language, set_qt_language
from mp4totext.gui.processing_history import format_duration


def test_translation_placeholders_match() -> None:
    for key, translations in _STRINGS.items():
        assert set(translations) == set(Language), key
        fields = [
            {field for _, field, _, _ in Formatter().parse(text) if field is not None}
            for text in translations.values()
        ]
        assert fields[0] == fields[1], key


@pytest.mark.parametrize("seconds, expected", [(9.6, "10s"), (90, "1m 30s"), (3661, "1h 01m 01s")])
def test_english_duration(seconds: float, expected: str) -> None:
    assert format_duration(seconds, Language.EN) == expected


def test_qt_standard_buttons_follow_language(qtbot: QtBot) -> None:
    try:
        set_qt_language(Language.JA)
        japanese = QCoreApplication.translate("QPlatformTheme", "Cancel")
        assert japanese == "キャンセル"
        set_qt_language(Language.EN)
        assert QCoreApplication.translate("QPlatformTheme", "Cancel") == "Cancel"
        set_qt_language(Language.JA)
        assert QCoreApplication.translate("QPlatformTheme", "Cancel") == japanese
    finally:
        set_qt_language(Language.EN)
