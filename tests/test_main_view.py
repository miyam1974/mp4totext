from pytestqt.qtbot import QtBot

from mp4totext.gui.file_queue_list import FileQueueList
from mp4totext.gui.i18n import Language, Translator
from mp4totext.gui.main_view import MainView


def test_language_and_destination_selections_are_independent(qtbot: QtBot) -> None:
    view = MainView(Translator(Language.JA), False, "output")
    qtbot.addWidget(view)
    view.lang_en_button.setChecked(True)
    assert not view.lang_ja_button.isChecked()
    assert view.custom_folder_radio.isChecked()
    view.same_folder_radio.setChecked(True)
    assert not view.custom_folder_radio.isChecked()
    assert view.lang_en_button.isChecked()
    view.lang_ja_button.setChecked(True)
    assert view.same_folder_radio.isChecked()


def test_size_measurement_preserves_existing_queue_items(qtbot: QtBot) -> None:
    widget = FileQueueList()
    qtbot.addWidget(widget)
    widget.addItems(["first.mp4", "second.mp4"])
    widget.setCurrentRow(1)
    assert widget.sizeHint().height() > 0
    assert [widget.item(i).text() for i in range(widget.count())] == ["first.mp4", "second.mp4"]
    assert widget.currentRow() == 1
