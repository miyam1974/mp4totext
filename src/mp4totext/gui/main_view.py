from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QRadioButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from mp4totext.gui.file_queue_list import FileQueueList
from mp4totext.gui.i18n import Language, Translator

_ROW_LABEL_WIDTH = 88


class MainView(QWidget):
    """Build and translate widgets; application behavior belongs to MainWindow."""

    def __init__(self, translator: Translator, same_folder: bool, output_dir: str) -> None:
        super().__init__()
        self._i18n = translator
        self._retranslators: list[Callable[[], None]] = []
        self._build_ui(same_folder, output_dir)

    def t(self, key: str, **kwargs: object) -> str:
        return self._i18n.t(key, **kwargs)

    def retranslate(self) -> None:
        for update in self._retranslators:
            update()

    def update_controls(
        self, *, running: bool, has_pending: bool, cancelling: bool, model_downloaded: bool,
    ) -> None:
        self.start_button.setEnabled(not running and has_pending)
        self.cancel_button.setEnabled(running and not cancelling)
        self.model_combo.setEnabled(not running)
        self.delete_model_button.setEnabled(not running and model_downloaded)
        self.delete_app_data_button.setEnabled(not running)
        self.exit_button.setEnabled(not running)
        for widget in (
            self.txt_check, self.json_check, self.same_folder_radio, self.custom_folder_radio,
        ):
            widget.setEnabled(not running)
        custom_folder = not running and not self.same_folder_radio.isChecked()
        for output_widget in (self.output_edit, self.output_browse_button, self.open_output_button):
            output_widget.setEnabled(custom_folder)

    def _tr(self, setter: Callable[[str], None], key: str, **kwargs: object) -> None:
        def update() -> None:
            setter(self.t(key, **kwargs))

        self._retranslators.append(update)
        update()

    def _row_label(self, key: str) -> QLabel:
        label = QLabel()
        label.setFixedWidth(_ROW_LABEL_WIDTH)
        self._tr(label.setText, key)
        return label

    def _build_ui(self, same_folder: bool, output_dir: str) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 10, 16, 10)
        root.setSpacing(5)

        title_row = QHBoxLayout()
        title = QLabel()
        title.setObjectName("title")
        self._tr(title.setText, "window_title")
        subtitle = QLabel()
        subtitle.setObjectName("subtitle")
        self._tr(subtitle.setText, "subtitle")
        title_row.addWidget(title)
        title_row.addSpacing(12)
        title_row.addWidget(subtitle)
        title_row.addStretch()
        self.lang_ja_button = QPushButton("JP")
        self.lang_ja_button.setObjectName("languageButton")
        self.lang_ja_button.setCheckable(True)
        self.lang_ja_button.setAutoExclusive(True)
        self.lang_ja_button.setChecked(self._i18n.language == Language.JA)
        self.lang_en_button = QPushButton("EN")
        self.lang_en_button.setObjectName("languageButton")
        self.lang_en_button.setCheckable(True)
        self.lang_en_button.setAutoExclusive(True)
        self.lang_en_button.setChecked(self._i18n.language == Language.EN)
        self.language_group = QButtonGroup(self)
        self.language_group.addButton(self.lang_ja_button)
        self.language_group.addButton(self.lang_en_button)
        title_row.addWidget(self.lang_en_button)
        title_row.addWidget(self.lang_ja_button)
        root.addLayout(title_row)

        source_row = QHBoxLayout()
        row_spacing = 8
        source_row.setSpacing(row_spacing)
        source_row.addWidget(self._row_label("label_video"), 0, Qt.AlignmentFlag.AlignTop)
        self.file_list = FileQueueList()
        self.file_list.setSpacing(0)
        self._tr(self.file_list.set_placeholder_text, "drop_hint")
        source_row.addWidget(self.file_list, 1)
        self.add_files_button = QPushButton()
        self._tr(self.add_files_button.setText, "add_files")
        source_row.addWidget(self.add_files_button, 0, Qt.AlignmentFlag.AlignTop)
        root.addLayout(source_row)

        queue_actions = QHBoxLayout()
        queue_actions.addSpacing(_ROW_LABEL_WIDTH + row_spacing)
        self.remove_button = QPushButton()
        self._tr(self.remove_button.setText, "remove")
        self.remove_button.setObjectName("compactButton")
        self.remove_button.setProperty("danger", True)
        self.move_up_button = QPushButton()
        self._tr(self.move_up_button.setText, "move_up")
        self.move_up_button.setObjectName("compactButton")
        self.move_down_button = QPushButton()
        self._tr(self.move_down_button.setText, "move_down")
        self.move_down_button.setObjectName("compactButton")
        queue_actions.addWidget(self.remove_button)
        queue_actions.addWidget(self.move_up_button)
        queue_actions.addWidget(self.move_down_button)
        self.open_source_folder_button = QPushButton()
        self._tr(self.open_source_folder_button.setText, "open_folder")
        self.open_source_folder_button.setObjectName("compactButton")
        queue_actions.addWidget(self.open_source_folder_button)
        queue_actions.addStretch()
        root.addLayout(queue_actions)

        output_row = QHBoxLayout()
        output_row.addWidget(self._row_label("label_destination"))
        self.same_folder_radio = QRadioButton()
        self._tr(self.same_folder_radio.setText, "same_folder")
        self.custom_folder_radio = QRadioButton()
        self._tr(self.custom_folder_radio.setText, "custom_folder")
        self.output_mode_group = QButtonGroup(self)
        self.output_mode_group.addButton(self.same_folder_radio)
        self.output_mode_group.addButton(self.custom_folder_radio)
        self.same_folder_radio.setChecked(same_folder)
        self.custom_folder_radio.setChecked(not same_folder)
        output_row.addWidget(self.same_folder_radio)
        output_row.addWidget(self.custom_folder_radio)
        self.output_edit = QLineEdit()
        self.output_edit.setText(output_dir)
        output_row.addWidget(self.output_edit, 1)
        self.output_browse_button = QPushButton()
        self._tr(self.output_browse_button.setText, "browse")
        output_row.addWidget(self.output_browse_button)
        self.open_output_button = QPushButton()
        self._tr(self.open_output_button.setText, "open")
        output_row.addWidget(self.open_output_button)
        root.addLayout(output_row)

        settings_row = QHBoxLayout()
        settings_row.addWidget(self._row_label("label_output_format"))
        self.txt_check = QCheckBox("TXT")
        self.json_check = QCheckBox("JSON")
        self.txt_check.setChecked(True)
        settings_row.addWidget(self.txt_check)
        settings_row.addWidget(self.json_check)
        settings_row.addSpacing(24)
        model_label = QLabel()
        self._tr(model_label.setText, "label_model")
        settings_row.addWidget(model_label)
        self.model_combo = QComboBox()
        self.model_combo.addItems(["tiny", "base", "small", "medium"])
        self.model_combo.setCurrentText("small")
        settings_row.addWidget(self.model_combo)
        self.model_description_label = QLabel()
        self.model_description_label.setObjectName("modelDescription")
        settings_row.addWidget(self.model_description_label)
        settings_row.addStretch()
        root.addLayout(settings_row)

        status_group = QGroupBox()
        status_group.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        status_layout = QVBoxLayout(status_group)
        status_layout.setSpacing(2)
        status_layout.setContentsMargins(8, 6, 8, 6)

        processing_row = QHBoxLayout()
        processing_row.addWidget(self._row_label("label_processing"), 0, Qt.AlignmentFlag.AlignTop)
        processing_content = QVBoxLayout()
        processing_content.setSpacing(0)
        self.active_file_label = QLabel()
        self.active_file_label.setObjectName("activeFile")
        self.timing_label = QLabel()
        self.timing_label.setObjectName("timing")
        processing_content.addWidget(self.active_file_label)
        processing_content.addWidget(self.timing_label)
        processing_row.addLayout(processing_content, 1)
        status_layout.addLayout(processing_row)

        status_row = QHBoxLayout()
        status_row.addWidget(self._row_label("label_state"))
        self.status_label = QLabel()
        status_row.addWidget(self.status_label, 1)
        status_layout.addLayout(status_row)

        model_row = QHBoxLayout()
        model_row.addWidget(self._row_label("label_model"))
        self.model_status_label = QLabel()
        self.model_status_label.setObjectName("modelStatus")
        model_row.addWidget(self.model_status_label, 1)
        self.delete_model_button = QPushButton()
        self._tr(self.delete_model_button.setText, "delete_selected_model")
        model_row.addWidget(self.delete_model_button)
        self.delete_app_data_button = QPushButton()
        self._tr(self.delete_app_data_button.setText, "delete_app_data")
        model_row.addWidget(self.delete_app_data_button)
        status_layout.addLayout(model_row)

        debug_row = QHBoxLayout()
        debug_row.addWidget(self._row_label("label_debug"), 0, Qt.AlignmentFlag.AlignTop)
        self.debug_output = QPlainTextEdit()
        self.debug_output.setReadOnly(True)
        self.debug_output.setFixedHeight(self.debug_output.fontMetrics().height() * 2 + 8)
        self._tr(self.debug_output.setPlaceholderText, "debug_placeholder")
        self.debug_output.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        debug_row.addWidget(self.debug_output, 1)
        status_layout.addLayout(debug_row)
        root.addWidget(status_group)

        actions = QHBoxLayout()
        actions.addStretch()
        self.cancel_button = QPushButton()
        self._tr(self.cancel_button.setText, "cancel")
        self.cancel_button.setObjectName("cancelButton")
        self.cancel_button.setEnabled(False)
        self.exit_button = QPushButton()
        self._tr(self.exit_button.setText, "exit")
        self.start_button = QPushButton()
        self._tr(self.start_button.setText, "start")
        self.start_button.setObjectName("primaryButton")
        self.start_button.setEnabled(False)
        actions.addWidget(self.exit_button)
        actions.addWidget(self.cancel_button)
        actions.addWidget(self.start_button)
        root.addLayout(actions)

