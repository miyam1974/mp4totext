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
from mp4totext.gui.job_controller import TranscriptionWorker
from mp4totext.gui.processing_history import (
    ProcessingMetrics,
    append_history,
    estimate_seconds,
    format_duration,
    load_history,
)


class QueueState(StrEnum):
    PENDING = "待機"
    ACTIVE = "処理中"
    COMPLETED = "完了"
    FAILED = "失敗"


_MODEL_DESCRIPTIONS = {
    "tiny": "最も軽量・高速",
    "base": "軽量",
    "small": "既定値。速度と精度のバランスを優先",
    "medium": "高精度だが処理時間とメモリ使用量が増加",
}

# Fixed width applied to every row label so each row's content starts at the
# same x position, matching the widest label ("出力形式").
_ROW_LABEL_WIDTH = 64


def _row_label(text: str) -> QLabel:
    label = QLabel(text)
    label.setFixedWidth(_ROW_LABEL_WIDTH)
    return label


class FileQueueList(QListWidget):
    """File list that doubles as the MP4 drag-and-drop target."""

    files_dropped = Signal(object)
    _PLACEHOLDER_TEXT = "複数のMP4ファイルをここにドロップ（または右のボタンで指定）"

    def __init__(self) -> None:
        super().__init__()
        self.setAcceptDrops(True)
        self.viewport().setAcceptDrops(True)
        self.setObjectName("fileList")
        self._visible_rows = 5
        self._cached_row_height: int | None = None
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

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
            self._PLACEHOLDER_TEXT,
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
        self._timing_started_at: float | None = None
        self._estimated_seconds: float | None = None
        self._active_file_size = 0
        self._elapsed_timer = QTimer(self)
        self._elapsed_timer.setInterval(1000)
        self._elapsed_timer.timeout.connect(self._update_elapsed_time)
        self.setWindowTitle("MP4 to Text")
        self.setMinimumSize(680, 460)
        self.resize(720, 560)
        self._sources: list[Path] = []
        self._states: list[QueueState] = []
        self._thread: QThread | None = None
        self._worker: TranscriptionWorker | None = None
        self._model_refresh_pending = False
        self._build_ui()

    def _build_ui(self) -> None:
        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(16, 10, 16, 10)
        root.setSpacing(5)

        title_row = QHBoxLayout()
        title = QLabel("MP4 to Text")
        title.setObjectName("title")
        subtitle = QLabel("動画を外部へ送信せず、このPCで文字起こしします")
        subtitle.setObjectName("subtitle")
        title_row.addWidget(title)
        title_row.addSpacing(12)
        title_row.addWidget(subtitle)
        title_row.addStretch()
        root.addLayout(title_row)

        source_row = QHBoxLayout()
        row_spacing = 8
        source_row.setSpacing(row_spacing)
        source_row.addWidget(_row_label("動画"), 0, Qt.AlignmentFlag.AlignTop)
        self.file_list = FileQueueList()
        self.file_list.setSpacing(0)
        self.file_list.files_dropped.connect(self._add_sources)
        self.file_list.currentRowChanged.connect(self._update_queue_buttons)
        source_row.addWidget(self.file_list, 1)
        self.add_files_button = QPushButton("MP4を追加")
        self.add_files_button.clicked.connect(self._choose_source)
        source_row.addWidget(self.add_files_button, 0, Qt.AlignmentFlag.AlignTop)
        root.addLayout(source_row)

        queue_actions = QHBoxLayout()
        queue_actions.addSpacing(_ROW_LABEL_WIDTH + row_spacing)
        self.remove_button = QPushButton("削除")
        self.remove_button.setObjectName("compactButton")
        self.remove_button.setProperty("danger", True)
        self.remove_button.clicked.connect(self._remove_selected)
        self.move_up_button = QPushButton("上へ")
        self.move_up_button.setObjectName("compactButton")
        self.move_up_button.clicked.connect(lambda: self._move_selected(-1))
        self.move_down_button = QPushButton("下へ")
        self.move_down_button.setObjectName("compactButton")
        self.move_down_button.clicked.connect(lambda: self._move_selected(1))
        queue_actions.addWidget(self.remove_button)
        queue_actions.addWidget(self.move_up_button)
        queue_actions.addWidget(self.move_down_button)
        self.open_source_folder_button = QPushButton("フォルダを開く")
        self.open_source_folder_button.setObjectName("compactButton")
        self.open_source_folder_button.clicked.connect(self._open_source_folder)
        queue_actions.addWidget(self.open_source_folder_button)
        queue_actions.addStretch()
        root.addLayout(queue_actions)

        output_row = QHBoxLayout()
        output_row.addWidget(_row_label("保存先"))
        self.same_folder_radio = QRadioButton("動画と同じフォルダ")
        self.custom_folder_radio = QRadioButton("指定フォルダ")
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
        self.output_browse_button = QPushButton("参照")
        self.output_browse_button.clicked.connect(self._choose_output_dir)
        output_row.addWidget(self.output_browse_button)
        self.open_output_button = QPushButton("開く")
        self.open_output_button.clicked.connect(self._open_output_dir)
        output_row.addWidget(self.open_output_button)
        root.addLayout(output_row)
        self._update_output_mode()

        settings_row = QHBoxLayout()
        settings_row.addWidget(_row_label("出力形式"))
        self.txt_check = QCheckBox("TXT")
        self.json_check = QCheckBox("JSON")
        self.txt_check.setChecked(True)
        self.txt_check.toggled.connect(self._refresh_queue_display)
        self.json_check.toggled.connect(self._refresh_queue_display)
        settings_row.addWidget(self.txt_check)
        settings_row.addWidget(self.json_check)
        settings_row.addSpacing(24)
        settings_row.addWidget(QLabel("モデル"))
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
        processing_row.addWidget(_row_label("処理中"), 0, Qt.AlignmentFlag.AlignTop)
        processing_content = QVBoxLayout()
        processing_content.setSpacing(0)
        self.active_file_label = QLabel("なし")
        self.active_file_label.setObjectName("activeFile")
        self.timing_label = QLabel("サイズ: - / 予測: - / 経過: -")
        self.timing_label.setObjectName("timing")
        processing_content.addWidget(self.active_file_label)
        processing_content.addWidget(self.timing_label)
        processing_row.addLayout(processing_content, 1)
        status_layout.addLayout(processing_row)

        status_row = QHBoxLayout()
        status_row.addWidget(_row_label("状態"))
        self.status_label = QLabel("MP4ファイルを選択してください")
        status_row.addWidget(self.status_label, 1)
        status_layout.addLayout(status_row)

        model_row = QHBoxLayout()
        model_row.addWidget(_row_label("モデル"))
        self.model_status_label = QLabel()
        self.model_status_label.setObjectName("modelStatus")
        model_row.addWidget(self.model_status_label, 1)
        self.delete_model_button = QPushButton("選択モデルを削除")
        self.delete_model_button.clicked.connect(self._delete_selected_model)
        model_row.addWidget(self.delete_model_button)
        self.delete_app_data_button = QPushButton("アプリ情報を削除")
        self.delete_app_data_button.clicked.connect(self._delete_app_data)
        model_row.addWidget(self.delete_app_data_button)
        status_layout.addLayout(model_row)

        debug_row = QHBoxLayout()
        debug_row.addWidget(QLabel("デバッグ"), 0, Qt.AlignmentFlag.AlignTop)
        self.debug_output = QPlainTextEdit()
        self.debug_output.setReadOnly(True)
        self.debug_output.setFixedHeight(self.debug_output.fontMetrics().height() * 2 + 8)
        self.debug_output.setPlaceholderText("エラーの詳細がここに表示されます")
        self.debug_output.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        debug_row.addWidget(self.debug_output, 1)
        status_layout.addLayout(debug_row)
        root.addWidget(status_group)

        actions = QHBoxLayout()
        actions.addStretch()
        self.cancel_button = QPushButton("キャンセル")
        self.cancel_button.setObjectName("cancelButton")
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self._cancel)
        self.exit_button = QPushButton("終了")
        self.exit_button.clicked.connect(self.close)
        self.start_button = QPushButton("文字起こしを開始")
        self.start_button.setObjectName("primaryButton")
        self.start_button.setEnabled(False)
        self.start_button.clicked.connect(self._start)
        actions.addWidget(self.exit_button)
        actions.addWidget(self.cancel_button)
        actions.addWidget(self.start_button)
        root.addLayout(actions)

        self.setCentralWidget(central)
        self.setStyleSheet(_STYLESHEET)
        self._update_queue_buttons()
        self._update_model_status()
        self._update_model_description()

    def _choose_source(self) -> None:
        file_names, _ = QFileDialog.getOpenFileNames(self, "MP4を選択", "", "MP4 (*.mp4)")
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
        self.status_label.setText(f"{len(self._sources)} ファイルを選択中")
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
        self.status_label.setText(f"{len(self._sources)} ファイルを選択中")
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
            QMessageBox.warning(self, "フォルダ", f"フォルダーが見つかりません。\n{directory}")
            return
        try:
            os.startfile(directory.resolve())
        except OSError as error:
            self._append_debug(f"フォルダを開けませんでした\n{traceback.format_exc()}")
            QMessageBox.critical(self, "フォルダ", str(error))

    def _choose_output_dir(self) -> None:
        directory = QFileDialog.getExistingDirectory(self, "保存先を選択")
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
            QMessageBox.warning(self, "保存先", f"フォルダーが見つかりません。\n{directory}")
            return
        try:
            os.startfile(directory.resolve())
        except OSError as error:
            self._append_debug(f"保存先を開けませんでした\n{traceback.format_exc()}")
            QMessageBox.critical(self, "保存先", str(error))

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
            QMessageBox.warning(self, "出力形式", "出力形式を1つ以上選択してください。")
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
            "上書き確認",
            "既存の出力ファイルを上書きしますか？",
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
        self.cancel_button.setText("キャンセル")
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
        self.active_file_label.setText(f"{source.name} ({index}/{total})")
        self._active_file_size = file_size
        self._estimated_seconds = estimate_seconds(
            self.model_combo.currentText(),
            file_size,
            load_history(self._settings),
        )
        self._timing_started_at = self._clock()
        self._elapsed_timer.start()
        self._update_elapsed_time()

    def _on_progress(self, event: ProgressEvent) -> None:
        self.status_label.setText(event.message)
        if event.stage is ProgressStage.DOWNLOADING_MODEL:
            self._model_refresh_pending = True
            self.cancel_button.setEnabled(True)
            self.cancel_button.setText("モデル取得をキャンセル")
            if event.fraction is None:
                model_state = "準備中"
            else:
                model_state = f"ダウンロード中 ({event.fraction:.0%})"
            self.model_status_label.setText(f"{self.model_combo.currentText()} / {model_state}")
        elif event.stage is ProgressStage.TRANSCRIBING and self._model_refresh_pending:
            self._model_refresh_pending = False
            self.cancel_button.setText("キャンセル")
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
        self.active_file_label.setText("なし")
        self.status_label.setText(f"完了: {completed}件 / 失敗: {failed}件")
        QMessageBox.information(
            self,
            "文字起こし完了",
            f"{completed}件を文字起こししました。失敗: {failed}件",
        )

    def _on_cancelled(self) -> None:
        self._finish_timing()
        self._model_refresh_pending = False
        self.status_label.setText("キャンセルしました")
        self.active_file_label.setText("なし")
        for row, state in enumerate(self._states):
            if state is QueueState.ACTIVE:
                self._states[row] = QueueState.PENDING
        self._refresh_queue_display()

    def _cancel(self) -> None:
        if self._worker is not None:
            self.status_label.setText("キャンセルしています")
            self.cancel_button.setEnabled(False)
            self._worker.cancel()

    def _job_finished(self) -> None:
        self._thread = None
        self._worker = None
        self._set_running(False)
        self._update_model_status()

    def _update_elapsed_time(self) -> None:
        elapsed = (
            max(self._clock() - self._timing_started_at, 0.0)
            if self._timing_started_at is not None
            else 0.0
        )
        estimate = (
            format_duration(self._estimated_seconds)
            if self._estimated_seconds is not None
            else "履歴なし"
        )
        self.timing_label.setText(
            f"サイズ: {format_size(self._active_file_size)} / "
            f"予測: {estimate} / 経過: {format_duration(elapsed)}"
        )

    def _finish_timing(self, elapsed_seconds: float | None = None) -> None:
        self._elapsed_timer.stop()
        if elapsed_seconds is None and self._timing_started_at is not None:
            elapsed_seconds = max(self._clock() - self._timing_started_at, 0.0)
        if elapsed_seconds is not None:
            estimate = (
                format_duration(self._estimated_seconds)
                if self._estimated_seconds is not None
                else "履歴なし"
            )
            self.timing_label.setText(
                f"サイズ: {format_size(self._active_file_size)} / "
                f"予測: {estimate} / 経過: {format_duration(elapsed_seconds)}"
            )
        self._timing_started_at = None

    def _update_model_description(self) -> None:
        self.model_description_label.setText(
            _MODEL_DESCRIPTIONS.get(self.model_combo.currentText(), "")
        )

    def _update_model_status(self) -> None:
        model_name = self.model_combo.currentText()
        try:
            status = inspect_model_cache(model_name)
        except Exception:
            self.model_status_label.setText(f"{model_name} / 状態確認エラー")
            self.delete_model_button.setEnabled(False)
            self._append_debug(f"モデル状態の確認に失敗しました\n{traceback.format_exc()}")
            return
        if status.downloaded:
            text = f"{model_name} / ダウンロード済み ({format_size(status.size_bytes)})"
        else:
            text = f"{model_name} / 未ダウンロード"
        self.model_status_label.setText(text)
        self.delete_model_button.setEnabled(status.downloaded and self._thread is None)

    def _delete_selected_model(self) -> None:
        model_name = self.model_combo.currentText()
        if QMessageBox.question(
            self,
            "モデル削除",
            f"ダウンロード済みの {model_name} モデルを削除しますか？",
        ) != QMessageBox.StandardButton.Yes:
            return
        try:
            delete_model_cache(model_name)
        except (OSError, RuntimeError) as error:
            self._append_debug(f"モデル削除に失敗しました\n{traceback.format_exc()}")
            QMessageBox.critical(self, "モデル削除エラー", str(error))
            return
        self._update_model_status()

    def _delete_app_data(self) -> None:
        if QMessageBox.question(
            self,
            "アプリ情報の削除",
            "ダウンロード済みモデルを含む、このアプリのキャッシュをすべて削除しますか？",
        ) != QMessageBox.StandardButton.Yes:
            return
        try:
            delete_app_cache()
        except (OSError, RuntimeError) as error:
            self._append_debug(f"アプリ情報削除に失敗しました\n{traceback.format_exc()}")
            QMessageBox.critical(self, "アプリ情報削除エラー", str(error))
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
        if self._is_transcribed(source):
            return (
                f"[{state.value} / 文字起こし済み] {source.name} "
                f"({size_text}) / 予測: {prediction}"
            )
        return f"[{state.value}] {source.name} ({size_text}) / 予測: {prediction}"

    @staticmethod
    def _file_size_text(source: Path) -> str:
        try:
            size_bytes = source.stat().st_size
        except OSError:
            return "算出不可"
        return f"{size_bytes / (1024 * 1024):.1f} MB"

    def _prediction_text(self, source: Path) -> str:
        try:
            file_size = source.stat().st_size
        except OSError:
            return "算出不可"
        predicted = estimate_seconds(
            self.model_combo.currentText(),
            file_size,
            load_history(self._settings),
        )
        return format_duration(predicted) if predicted is not None else "履歴なし"

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

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._thread is not None and self._thread.isRunning():
            QMessageBox.information(
                self,
                "処理中",
                "文字起こしをキャンセルしてから終了してください。",
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
