import os
import time
import traceback
from collections.abc import Callable
from enum import StrEnum
from pathlib import Path

from PySide6.QtCore import QRect, QSettings, QSize, QStandardPaths, Qt, QThread, QTimer, Signal
from PySide6.QtGui import (
    QCloseEvent,
    QColor,
    QDragEnterEvent,
    QDragMoveEvent,
    QDropEvent,
    QPainter,
    QPaintEvent,
)
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QRadioButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from mp4totext.application import OutputFormat, TranscriptionResult
from mp4totext.domain import ProgressEvent, ProgressStage, TranscriptionOptions
from mp4totext.engine.model_cache import (
    delete_app_cache,
    delete_model_cache,
    format_size,
    inspect_model_cache,
)
from mp4totext.gui.i18n import Language, Translator, set_qt_language
from mp4totext.gui.job_controller import TranscriptionWorker
from mp4totext.gui.processing_history import (
    ProcessingMetrics,
    append_history,
    estimate_seconds,
    format_duration,
    load_history,
)


class QueueState(StrEnum):
    PENDING = "pending"
    ACTIVE = "active"
    COMPLETED = "completed"
    FAILED = "failed"


_QUEUE_STATE_KEYS = {
    QueueState.PENDING: "queue_pending",
    QueueState.ACTIVE: "queue_active",
    QueueState.COMPLETED: "queue_completed",
    QueueState.FAILED: "queue_failed",
}

_MODEL_DESCRIPTION_KEYS = {
    "tiny": "model_description_tiny",
    "base": "model_description_base",
    "small": "model_description_small",
    "medium": "model_description_medium",
}

_STAGE_KEYS = {
    ProgressStage.PREPARING: "stage_preparing",
    ProgressStage.DOWNLOADING_MODEL: "stage_downloading_model",
    ProgressStage.TRANSCRIBING: "stage_transcribing",
    ProgressStage.SAVING: "stage_saving",
    ProgressStage.COMPLETED: "stage_completed",
}

# Fixed width applied to every row label so each row's content starts at the
# same x position, matching the widest label ("出力形式" / "Output").
_ROW_LABEL_WIDTH = 88


class FileQueueList(QListWidget):
    """File list that doubles as the MP4 drag-and-drop target."""

    files_dropped = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self.setAcceptDrops(True)
        self.viewport().setAcceptDrops(True)
        self.setObjectName("fileList")
        self._visible_rows = 5
        self._cached_row_height: int | None = None
        self._placeholder_text = ""
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

    def set_placeholder_text(self, text: str) -> None:
        self._placeholder_text = text
        self.viewport().update()

    def sizeHint(self) -> QSize:
        width = super().sizeHint().width()
        return QSize(width, self._row_height() * self._visible_rows)

    def _row_height(self) -> int:
        # Measure Qt's real per-item height (includes delegate/DPI overhead
        # that a plain font-metrics estimate misses) via a throwaway item,
        # caching the result since sizeHint() can be queried very often.
        if self._cached_row_height is None:
            self.addItem("")
            height = self.sizeHintForRow(0)
            self.takeItem(0)
            self._cached_row_height = height if height > 0 else self.fontMetrics().height() + 8
        return self._cached_row_height

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if self._is_acceptable(event):
            event.acceptProposedAction()

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:
        # QAbstractItemView's own dragMoveEvent rejects drags that aren't its
        # internal item-reordering mime type, so external file drags need it
        # explicitly re-accepted here to keep dropEvent from being cancelled.
        if self._is_acceptable(event):
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:
        if not self._is_acceptable(event):
            return
        sources = tuple(Path(url.toLocalFile()) for url in event.mimeData().urls())
        self.files_dropped.emit(sources)
        event.acceptProposedAction()

    @staticmethod
    def _is_acceptable(event: QDragEnterEvent | QDragMoveEvent | QDropEvent) -> bool:
        urls = event.mimeData().urls()
        return bool(urls) and all(Path(url.toLocalFile()).suffix.lower() == ".mp4" for url in urls)

    def paintEvent(self, event: QPaintEvent) -> None:
        super().paintEvent(event)
        viewport_rect = self.viewport().rect()
        if self.count() == 0:
            empty_top = viewport_rect.top()
        else:
            last_row_bottom = self.visualItemRect(self.item(self.count() - 1)).bottom()
            empty_top = max(last_row_bottom, viewport_rect.top())
        empty_rect = QRect(
            viewport_rect.left(),
            empty_top,
            viewport_rect.width(),
            viewport_rect.bottom() - empty_top,
        )
        if empty_rect.height() < 8:
            return
        painter = QPainter(self.viewport())
        painter.setPen(QColor("#526258"))
        painter.drawText(
            empty_rect,
            int(Qt.AlignmentFlag.AlignCenter) | int(Qt.TextFlag.TextWordWrap),
            self._placeholder_text,
        )


class MainWindow(QMainWindow):
    def __init__(
        self,
        settings: QSettings | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        super().__init__()
        self._settings = settings or QSettings("mp4totext", "mp4totext")
        self._clock = clock
        saved_language = str(self._settings.value("app/language", Language.JA.value, type=str))
        language = Language.EN if saved_language == Language.EN.value else Language.JA
        self._i18n = Translator(language)
        set_qt_language(language)
        self._retranslators: list[Callable[[], None]] = []
        self._status_state: tuple[str, dict[str, object]] | None = None
        self._active_file_state: tuple[str, dict[str, object]] | None = None
        self._timing_started_at: float | None = None
        self._finished_elapsed: float | None = None
        self._download_fraction: float | None = None
        self._estimated_seconds: float | None = None
        self._active_file_size = 0
        self._elapsed_timer = QTimer(self)
        self._elapsed_timer.setInterval(1000)
        self._elapsed_timer.timeout.connect(self._update_elapsed_time)
        self.setMinimumSize(680, 460)
        self.resize(720, 560)
        self._sources: list[Path] = []
        self._states: list[QueueState] = []
        self._thread: QThread | None = None
        self._worker: TranscriptionWorker | None = None
        self._model_refresh_pending = False
        self._build_ui()

    def t(self, key: str, **kwargs: object) -> str:
        return self._i18n.t(key, **kwargs)

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

    def _set_language(self, language: Language) -> None:
        if language == self._i18n.language:
            return
        self._i18n.language = language
        set_qt_language(language)
        self._settings.setValue("app/language", language.value)
        self._retranslate()

    def _on_ja_toggled(self, checked: bool) -> None:
        if checked:
            self._set_language(Language.JA)

    def _on_en_toggled(self, checked: bool) -> None:
        if checked:
            self._set_language(Language.EN)

    def _retranslate(self) -> None:
        for update in self._retranslators:
            update()
        if self._status_state is not None:
            key, kwargs = self._status_state
            self.status_label.setText(self.t(key, **kwargs))
        if self._active_file_state is not None:
            key, kwargs = self._active_file_state
            self.active_file_label.setText(self.t(key, **kwargs))
        self._update_elapsed_time()
        self.cancel_button.setText(
            self.t("cancel_model_download") if self._model_refresh_pending else self.t("cancel")
        )
        self._update_model_status()
        self._update_model_description()
        self._refresh_queue_display()

    def _set_status(self, key: str, **kwargs: object) -> None:
        self._status_state = (key, kwargs)
        self.status_label.setText(self.t(key, **kwargs))

    def _set_active_file(self, key: str, **kwargs: object) -> None:
        self._active_file_state = (key, kwargs)
        self.active_file_label.setText(self.t(key, **kwargs))

    def _build_ui(self) -> None:
        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(16, 10, 16, 10)
        root.setSpacing(5)

        title_row = QHBoxLayout()
        title = QLabel()
        title.setObjectName("title")
        self._tr(title.setText, "window_title")
        self._tr(self.setWindowTitle, "window_title")
        subtitle = QLabel()
        subtitle.setObjectName("subtitle")
        self._tr(subtitle.setText, "subtitle")
        title_row.addWidget(title)
        title_row.addSpacing(12)
        title_row.addWidget(subtitle)
        title_row.addStretch()
        self.lang_ja_button = QPushButton("JP")
        self.lang_ja_button.setObjectName("compactButton")
        self.lang_ja_button.setCheckable(True)
        self.lang_ja_button.setAutoExclusive(True)
        self.lang_ja_button.setChecked(self._i18n.language == Language.JA)
        self.lang_ja_button.toggled.connect(self._on_ja_toggled)
        self.lang_en_button = QPushButton("EN")
        self.lang_en_button.setObjectName("compactButton")
        self.lang_en_button.setCheckable(True)
        self.lang_en_button.setAutoExclusive(True)
        self.lang_en_button.setChecked(self._i18n.language == Language.EN)
        self.lang_en_button.toggled.connect(self._on_en_toggled)
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
        self.file_list.files_dropped.connect(self._add_sources)
        self.file_list.currentRowChanged.connect(self._update_queue_buttons)
        source_row.addWidget(self.file_list, 1)
        self.add_files_button = QPushButton()
        self._tr(self.add_files_button.setText, "add_files")
        self.add_files_button.clicked.connect(self._choose_source)
        source_row.addWidget(self.add_files_button, 0, Qt.AlignmentFlag.AlignTop)
        root.addLayout(source_row)

        queue_actions = QHBoxLayout()
        queue_actions.addSpacing(_ROW_LABEL_WIDTH + row_spacing)
        self.remove_button = QPushButton()
        self._tr(self.remove_button.setText, "remove")
        self.remove_button.setObjectName("compactButton")
        self.remove_button.setProperty("danger", True)
        self.remove_button.clicked.connect(self._remove_selected)
        self.move_up_button = QPushButton()
        self._tr(self.move_up_button.setText, "move_up")
        self.move_up_button.setObjectName("compactButton")
        self.move_up_button.clicked.connect(lambda: self._move_selected(-1))
        self.move_down_button = QPushButton()
        self._tr(self.move_down_button.setText, "move_down")
        self.move_down_button.setObjectName("compactButton")
        self.move_down_button.clicked.connect(lambda: self._move_selected(1))
        queue_actions.addWidget(self.remove_button)
        queue_actions.addWidget(self.move_up_button)
        queue_actions.addWidget(self.move_down_button)
        self.open_source_folder_button = QPushButton()
        self._tr(self.open_source_folder_button.setText, "open_folder")
        self.open_source_folder_button.setObjectName("compactButton")
        self.open_source_folder_button.clicked.connect(self._open_source_folder)
        queue_actions.addWidget(self.open_source_folder_button)
        queue_actions.addStretch()
        root.addLayout(queue_actions)

        output_row = QHBoxLayout()
        output_row.addWidget(self._row_label("label_destination"))
        self.same_folder_radio = QRadioButton()
        self._tr(self.same_folder_radio.setText, "same_folder")
        self.custom_folder_radio = QRadioButton()
        self._tr(self.custom_folder_radio.setText, "custom_folder")
        same_folder = bool(self._settings.value("output/same_folder", False, type=bool))
        self.same_folder_radio.setChecked(same_folder)
        self.custom_folder_radio.setChecked(not same_folder)
        self.same_folder_radio.toggled.connect(self._update_output_mode)
        output_row.addWidget(self.same_folder_radio)
        output_row.addWidget(self.custom_folder_radio)
        self.output_edit = QLineEdit()
        self.output_edit.setText(self._saved_output_dir())
        self.output_edit.editingFinished.connect(self._save_output_dir)
        self.output_edit.textChanged.connect(self._refresh_queue_display)
        output_row.addWidget(self.output_edit, 1)
        self.output_browse_button = QPushButton()
        self._tr(self.output_browse_button.setText, "browse")
        self.output_browse_button.clicked.connect(self._choose_output_dir)
        output_row.addWidget(self.output_browse_button)
        self.open_output_button = QPushButton()
        self._tr(self.open_output_button.setText, "open")
        self.open_output_button.clicked.connect(self._open_output_dir)
        output_row.addWidget(self.open_output_button)
        root.addLayout(output_row)
        self._update_output_mode()

        settings_row = QHBoxLayout()
        settings_row.addWidget(self._row_label("label_output_format"))
        self.txt_check = QCheckBox("TXT")
        self.json_check = QCheckBox("JSON")
        self.txt_check.setChecked(True)
        self.txt_check.toggled.connect(self._refresh_queue_display)
        self.json_check.toggled.connect(self._refresh_queue_display)
        settings_row.addWidget(self.txt_check)
        settings_row.addWidget(self.json_check)
        settings_row.addSpacing(24)
        model_label = QLabel()
        self._tr(model_label.setText, "label_model")
        settings_row.addWidget(model_label)
        self.model_combo = QComboBox()
        self.model_combo.addItems(["tiny", "base", "small", "medium"])
        self.model_combo.setCurrentText("small")
        self.model_combo.currentTextChanged.connect(self._update_model_status)
        self.model_combo.currentTextChanged.connect(self._update_model_description)
        self.model_combo.currentTextChanged.connect(self._refresh_queue_display)
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
        self.delete_model_button.clicked.connect(self._delete_selected_model)
        model_row.addWidget(self.delete_model_button)
        self.delete_app_data_button = QPushButton()
        self._tr(self.delete_app_data_button.setText, "delete_app_data")
        self.delete_app_data_button.clicked.connect(self._delete_app_data)
        model_row.addWidget(self.delete_app_data_button)
        status_layout.addLayout(model_row)

        debug_row = QHBoxLayout()
        debug_label = QLabel()
        self._tr(debug_label.setText, "label_debug")
        debug_row.addWidget(debug_label, 0, Qt.AlignmentFlag.AlignTop)
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
        self.cancel_button.clicked.connect(self._cancel)
        self.exit_button = QPushButton()
        self._tr(self.exit_button.setText, "exit")
        self.exit_button.clicked.connect(self.close)
        self.start_button = QPushButton()
        self._tr(self.start_button.setText, "start")
        self.start_button.setObjectName("primaryButton")
        self.start_button.setEnabled(False)
        self.start_button.clicked.connect(self._start)
        actions.addWidget(self.exit_button)
        actions.addWidget(self.cancel_button)
        actions.addWidget(self.start_button)
        root.addLayout(actions)

        self.setCentralWidget(central)
        self.setStyleSheet(_STYLESHEET)
        self._set_status("select_mp4_prompt")
        self._set_active_file("none")
        self.timing_label.setText(self.t("timing_placeholder"))
        self._update_queue_buttons()
        self._update_model_status()
        self._update_model_description()

    def _choose_source(self) -> None:
        file_names, _ = QFileDialog.getOpenFileNames(
            self, self.t("select_mp4_dialog_title"), "", "MP4 (*.mp4)",
            options=QFileDialog.Option.DontUseNativeDialog,
        )
        if file_names:
            self._add_sources(tuple(Path(file_name) for file_name in file_names))

    def _add_sources(self, sources: tuple[Path, ...]) -> None:
        added: list[Path] = []
        for source in sources:
            if source not in self._sources:
                self._sources.append(source)
                self._states.append(QueueState.PENDING)
                self.file_list.addItem(self._queue_text(source, QueueState.PENDING))
                added.append(source)
        if added and self._worker is not None:
            self._worker.add_pending(tuple(added))
        self._set_status("files_selected", count=len(self._sources))
        self.start_button.setEnabled(self._thread is None and bool(self._sources))
        self._update_queue_buttons()

    def _remove_selected(self) -> None:
        row = self.file_list.currentRow()
        if not self._is_removable(row):
            return
        source = self._sources[row]
        if (
            self._states[row] is QueueState.PENDING
            and self._worker is not None
            and not self._worker.remove_pending(source)
        ):
            return
        self.file_list.takeItem(row)
        self._sources.pop(row)
        self._states.pop(row)
        self._set_status("files_selected", count=len(self._sources))
        self.start_button.setEnabled(self._thread is None and self._has_pending())
        self._update_queue_buttons()

    def _move_selected(self, offset: int) -> None:
        row = self.file_list.currentRow()
        destination = row + offset
        if not self._is_pending(row) or not self._is_pending(destination):
            return
        self._sources[row], self._sources[destination] = (
            self._sources[destination],
            self._sources[row],
        )
        self._states[row], self._states[destination] = (
            self._states[destination],
            self._states[row],
        )
        item = self.file_list.takeItem(row)
        self.file_list.insertItem(destination, item)
        self.file_list.setCurrentRow(destination)
        if self._worker is not None:
            self._worker.reorder_pending(self._pending_sources())

    def _update_queue_buttons(self) -> None:
        row = self.file_list.currentRow()
        pending = self._is_pending(row)
        self.remove_button.setEnabled(self._is_removable(row))
        self.move_up_button.setEnabled(pending and self._is_pending(row - 1))
        self.move_down_button.setEnabled(pending and self._is_pending(row + 1))
        self.open_source_folder_button.setEnabled(0 <= row < len(self._sources))

    def _open_source_folder(self) -> None:
        row = self.file_list.currentRow()
        if not 0 <= row < len(self._sources):
            return
        directory = self._sources[row].parent
        if not directory.is_dir():
            QMessageBox.warning(
                self, self.t("folder_title"), self.t("folder_not_found", path=directory)
            )
            return
        try:
            os.startfile(directory.resolve())
        except OSError:
            self._append_debug(f"{self.t('folder_open_failed')}\n{traceback.format_exc()}")
            self._show_error("folder_title", "folder_open_failed")

    def _choose_output_dir(self) -> None:
        directory = QFileDialog.getExistingDirectory(
            self, self.t("select_destination_dialog_title"),
            options=QFileDialog.Option.ShowDirsOnly | QFileDialog.Option.DontUseNativeDialog,
        )
        if directory:
            self.output_edit.setText(directory)
            self._save_output_dir()

    def _update_output_mode(self) -> None:
        same_folder = self.same_folder_radio.isChecked()
        self.output_edit.setEnabled(not same_folder)
        self.output_browse_button.setEnabled(not same_folder)
        self.open_output_button.setEnabled(not same_folder)
        self._settings.setValue("output/same_folder", same_folder)
        self._refresh_queue_display()

    def _open_output_dir(self) -> None:
        directory = Path(self.output_edit.text().strip())
        if not directory.is_dir():
            QMessageBox.warning(
                self, self.t("destination_title"), self.t("folder_not_found", path=directory)
            )
            return
        try:
            os.startfile(directory.resolve())
        except OSError:
            self._append_debug(f"{self.t('destination_open_failed')}\n{traceback.format_exc()}")
            self._show_error("destination_title", "destination_open_failed")

    def _selected_formats(self) -> tuple[OutputFormat, ...]:
        selections = (
            (self.txt_check, OutputFormat.TXT),
            (self.json_check, OutputFormat.JSON),
        )
        return tuple(
            output_format for checkbox, output_format in selections if checkbox.isChecked()
        )

    def _start(self) -> None:
        pending_sources = self._pending_sources()
        if not pending_sources:
            return
        self._save_output_dir()
        formats = self._selected_formats()
        if not formats:
            QMessageBox.warning(
                self, self.t("output_format_title"), self.t("output_format_required")
            )
            return

        output_dir = (
            None
            if self.same_folder_radio.isChecked()
            else Path(self.output_edit.text())
            if self.output_edit.text()
            else None
        )
        existing = [
            (output_dir or source.parent) / f"{source.stem}.{item.value}"
            for source in pending_sources
            for item in formats
        ]
        overwrite = any(path.exists() for path in existing)
        if overwrite and QMessageBox.question(
            self,
            self.t("overwrite_confirm_title"),
            self.t("overwrite_confirm_message"),
        ) != QMessageBox.StandardButton.Yes:
            return

        self._set_running(True)
        self._thread = QThread(self)
        self._worker = TranscriptionWorker(
            pending_sources,
            output_dir,
            formats,
            TranscriptionOptions(model_name=self.model_combo.currentText()),
            overwrite,
        )
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.file_started.connect(self._on_file_started)
        self._worker.progress.connect(self._on_progress)
        self._worker.file_completed.connect(self._on_file_completed)
        self._worker.file_failed.connect(self._on_file_failed)
        self._worker.batch_completed.connect(self._on_batch_completed)
        self._worker.cancelled.connect(self._on_cancelled)
        self._worker.finished.connect(self._thread.quit)
        self._worker.finished.connect(self._worker.deleteLater)
        self._thread.finished.connect(self._job_finished)
        self._thread.finished.connect(self._thread.deleteLater)
        self._thread.start()

    def _set_running(self, running: bool) -> None:
        self.start_button.setEnabled(not running and self._has_pending())
        self.cancel_button.setEnabled(running)
        self.cancel_button.setText(self.t("cancel"))
        self.file_list.setEnabled(True)
        self.model_combo.setEnabled(not running)
        self.delete_model_button.setEnabled(not running)
        self.delete_app_data_button.setEnabled(not running)
        self.exit_button.setEnabled(not running)
        for checkbox in (self.txt_check, self.json_check):
            checkbox.setEnabled(not running)
        for radio in (self.same_folder_radio, self.custom_folder_radio):
            radio.setEnabled(not running)
        custom_folder = not running and self.custom_folder_radio.isChecked()
        self.output_edit.setEnabled(custom_folder)
        self.output_browse_button.setEnabled(custom_folder)
        self.open_output_button.setEnabled(custom_folder)
        self._update_queue_buttons()

    def _on_file_started(self, source: Path, index: int, total: int, file_size: int) -> None:
        row = self._sources.index(source)
        self._states[row] = QueueState.ACTIVE
        self.file_list.setCurrentRow(row)
        self.file_list.item(row).setText(self._queue_text(source, QueueState.ACTIVE))
        self._set_active_file("active_file_progress", name=source.name, index=index, total=total)
        self._active_file_size = file_size
        self._estimated_seconds = estimate_seconds(
            self.model_combo.currentText(),
            file_size,
            load_history(self._settings),
        )
        self._timing_started_at = self._clock()
        self._finished_elapsed = None
        self._elapsed_timer.start()
        self._update_elapsed_time()

    def _on_progress(self, event: ProgressEvent) -> None:
        stage_key = _STAGE_KEYS.get(event.stage)
        if stage_key is not None:
            self._set_status(stage_key)
        else:
            self.status_label.setText(event.message)
        if event.stage is ProgressStage.DOWNLOADING_MODEL:
            self._model_refresh_pending = True
            self._download_fraction = event.fraction
            self.cancel_button.setEnabled(True)
            self.cancel_button.setText(self.t("cancel_model_download"))
            if event.fraction is None:
                model_state = self.t("preparing")
            else:
                model_state = self.t("downloading", percent=f"{event.fraction:.0%}")
            self.model_status_label.setText(f"{self.model_combo.currentText()} / {model_state}")
        elif event.stage is ProgressStage.TRANSCRIBING and self._model_refresh_pending:
            self._model_refresh_pending = False
            self.cancel_button.setText(self.t("cancel"))
            self._update_model_status()

    def _on_file_completed(
        self,
        source: Path,
        result: TranscriptionResult,
        metrics: ProcessingMetrics,
    ) -> None:
        self._finish_timing(metrics.elapsed_seconds)
        if metrics.file_size_bytes > 0 and metrics.elapsed_seconds > 0:
            append_history(self._settings, metrics)
            self._settings.sync()
        row = self._sources.index(source)
        self._states[row] = QueueState.COMPLETED
        self.file_list.item(row).setText(self._queue_text(source, QueueState.COMPLETED))
        self.file_list.item(row).setToolTip("\n".join(str(path) for path in result.output_paths))
        self._refresh_queue_display()

    def _on_file_failed(self, source: Path, message: str) -> None:
        self._finish_timing()
        row = self._sources.index(source)
        self._states[row] = QueueState.FAILED
        self.file_list.item(row).setText(self._queue_text(source, QueueState.FAILED))
        self.file_list.item(row).setToolTip(message)
        self._append_debug(f"{source}\n{message}")

    def _on_batch_completed(self, completed: int, failed: int) -> None:
        self._set_active_file("none")
        self._set_status("batch_completed_status", completed=completed, failed=failed)
        QMessageBox.information(
            self,
            self.t("batch_completed_title"),
            self.t("batch_completed_message", completed=completed, failed=failed),
        )

    def _on_cancelled(self) -> None:
        self._finish_timing()
        self._model_refresh_pending = False
        self._set_status("cancelled_status")
        self._set_active_file("none")
        for row, state in enumerate(self._states):
            if state is QueueState.ACTIVE:
                self._states[row] = QueueState.PENDING
        self._refresh_queue_display()

    def _cancel(self) -> None:
        if self._worker is not None:
            self._set_status("cancelling_status")
            self.cancel_button.setEnabled(False)
            self._worker.cancel()

    def _job_finished(self) -> None:
        self._thread = None
        self._worker = None
        self._model_refresh_pending = False
        self._set_running(False)
        self._update_model_status()

    def _update_elapsed_time(self) -> None:
        if self._timing_started_at is None and self._finished_elapsed is None:
            self.timing_label.setText(self.t("timing_placeholder"))
            return
        elapsed = (
            max(self._clock() - self._timing_started_at, 0.0)
            if self._timing_started_at is not None
            else self._finished_elapsed or 0.0
        )
        estimate = (
            format_duration(self._estimated_seconds, self._i18n.language)
            if self._estimated_seconds is not None
            else self.t("history_none")
        )
        self.timing_label.setText(
            self.t(
                "timing_text",
                size=format_size(self._active_file_size),
                estimate=estimate,
                elapsed=format_duration(elapsed, self._i18n.language),
            )
        )

    def _finish_timing(self, elapsed_seconds: float | None = None) -> None:
        self._elapsed_timer.stop()
        if elapsed_seconds is None and self._timing_started_at is not None:
            elapsed_seconds = max(self._clock() - self._timing_started_at, 0.0)
        self._finished_elapsed = elapsed_seconds
        self._timing_started_at = None
        self._update_elapsed_time()

    def _update_model_description(self) -> None:
        key = _MODEL_DESCRIPTION_KEYS.get(self.model_combo.currentText())
        self.model_description_label.setText(self.t(key) if key is not None else "")

    def _update_model_status(self) -> None:
        model_name = self.model_combo.currentText()
        if self._model_refresh_pending:
            state = (
                self.t("preparing")
                if self._download_fraction is None
                else self.t("downloading", percent=f"{self._download_fraction:.0%}")
            )
            self.model_status_label.setText(f"{model_name} / {state}")
            return
        try:
            status = inspect_model_cache(model_name)
        except Exception:
            self.model_status_label.setText(f"{model_name} / {self.t('status_check_error')}")
            self.delete_model_button.setEnabled(False)
            self._append_debug(f"{self.t('model_status_failed_debug')}\n{traceback.format_exc()}")
            return
        if status.downloaded:
            text = f"{model_name} / {self.t('downloaded', size=format_size(status.size_bytes))}"
        else:
            text = f"{model_name} / {self.t('not_downloaded')}"
        self.model_status_label.setText(text)
        self.delete_model_button.setEnabled(status.downloaded and self._thread is None)

    def _delete_selected_model(self) -> None:
        model_name = self.model_combo.currentText()
        if QMessageBox.question(
            self,
            self.t("model_delete_title"),
            self.t("model_delete_confirm", model=model_name),
        ) != QMessageBox.StandardButton.Yes:
            return
        try:
            delete_model_cache(model_name)
        except (OSError, RuntimeError):
            self._append_debug(f"{self.t('model_delete_failed_debug')}\n{traceback.format_exc()}")
            self._show_error("model_delete_error_title", "model_delete_failed_debug")
            return
        self._update_model_status()

    def _delete_app_data(self) -> None:
        if QMessageBox.question(
            self,
            self.t("app_data_delete_title"),
            self.t("app_data_delete_confirm"),
        ) != QMessageBox.StandardButton.Yes:
            return
        try:
            delete_app_cache()
        except (OSError, RuntimeError):
            self._append_debug(
                f"{self.t('app_data_delete_failed_debug')}\n{traceback.format_exc()}"
            )
            self._show_error("app_data_delete_error_title", "app_data_delete_failed_debug")
            return
        self._settings.clear()
        self.output_edit.setText(self._default_output_dir())
        self._save_output_dir()
        self._update_model_status()

    def _has_pending(self) -> bool:
        return QueueState.PENDING in self._states

    def _pending_sources(self) -> tuple[Path, ...]:
        return tuple(
            source
            for source, state in zip(self._sources, self._states, strict=True)
            if state is QueueState.PENDING
        )

    def _is_pending(self, row: int) -> bool:
        return 0 <= row < len(self._states) and self._states[row] is QueueState.PENDING

    def _is_removable(self, row: int) -> bool:
        return 0 <= row < len(self._states) and self._states[row] is not QueueState.ACTIVE

    def _queue_text(self, source: Path, state: QueueState) -> str:
        size_text = self._file_size_text(source)
        prediction = self._prediction_text(source)
        state_text = self.t(_QUEUE_STATE_KEYS[state])
        if self._is_transcribed(source):
            return self.t(
                "queue_item_transcribed",
                state=state_text,
                transcribed=self.t("queue_transcribed"),
                name=source.name,
                size=size_text,
                prediction=prediction,
            )
        return self.t(
            "queue_item", state=state_text, name=source.name, size=size_text, prediction=prediction
        )

    def _file_size_text(self, source: Path) -> str:
        try:
            size_bytes = source.stat().st_size
        except OSError:
            return self.t("size_unavailable")
        return f"{size_bytes / (1024 * 1024):.1f} MB"

    def _prediction_text(self, source: Path) -> str:
        try:
            file_size = source.stat().st_size
        except OSError:
            return self.t("size_unavailable")
        predicted = estimate_seconds(
            self.model_combo.currentText(),
            file_size,
            load_history(self._settings),
        )
        return (
            format_duration(predicted, self._i18n.language)
            if predicted is not None else self.t("history_none")
        )

    def _refresh_queue_display(self) -> None:
        for row, (source, state) in enumerate(
            zip(self._sources, self._states, strict=True)
        ):
            self.file_list.item(row).setText(self._queue_text(source, state))

    def _is_transcribed(self, source: Path) -> bool:
        formats = self._selected_formats()
        if not formats:
            return False
        output_dir = (
            source.parent
            if self.same_folder_radio.isChecked()
            else Path(self.output_edit.text().strip())
        )
        return all((output_dir / f"{source.stem}.{item.value}").is_file() for item in formats)

    def _saved_output_dir(self) -> str:
        saved = str(self._settings.value("output/directory", "", type=str))
        return saved or self._default_output_dir()

    @staticmethod
    def _default_output_dir() -> str:
        documents = QStandardPaths.writableLocation(
            QStandardPaths.StandardLocation.DocumentsLocation
        )
        return documents or str(Path.home())

    def _save_output_dir(self) -> None:
        directory = self.output_edit.text().strip()
        if directory:
            self._settings.setValue("output/directory", directory)

    def _append_debug(self, details: str) -> None:
        if self.debug_output.toPlainText():
            self.debug_output.appendPlainText("\n" + "-" * 60)
        self.debug_output.appendPlainText(details.rstrip())
        scroll_bar = self.debug_output.verticalScrollBar()
        scroll_bar.setValue(scroll_bar.maximum())

    def _show_error(self, title_key: str, message_key: str) -> None:
        QMessageBox.critical(
            self, self.t(title_key),
            f"{self.t(message_key)}\n{self.t('error_details_hint')}",
        )

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._thread is not None and self._thread.isRunning():
            QMessageBox.information(
                self,
                self.t("processing_in_progress_title"),
                self.t("processing_in_progress_message"),
            )
            event.ignore()
            return
        self._save_output_dir()
        event.accept()


_STYLESHEET = """
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
QPushButton#compactButton {
    min-height: 16px;
    font-size: 10px;
    padding: 0 6px;
}
QPushButton#compactButton:checkable:checked {
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
