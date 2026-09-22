import os
import time
import traceback
from collections.abc import Callable
from enum import StrEnum
from pathlib import Path

from PySide6.QtCore import QSettings, QStandardPaths, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QCloseEvent, QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
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


class DropArea(QFrame):
    files_dropped = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self.setAcceptDrops(True)
        self.setObjectName("dropArea")
        self.setFixedHeight(54)
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.label = QLabel("複数のMP4ファイルをここにドロップ")
        self.label.setObjectName("dropTitle")
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.label)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        urls = event.mimeData().urls()
        if urls and all(Path(url.toLocalFile()).suffix.lower() == ".mp4" for url in urls):
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:
        sources = tuple(Path(url.toLocalFile()) for url in event.mimeData().urls())
        self.files_dropped.emit(sources)
        event.acceptProposedAction()


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
        self.setMinimumSize(680, 500)
        self.resize(720, 604)
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
        self.drop_area = DropArea()
        self.drop_area.files_dropped.connect(self._add_sources)
        source_row.addWidget(self.drop_area, 1)
        self.add_files_button = QPushButton("MP4を追加")
        self.add_files_button.clicked.connect(self._choose_source)
        source_row.addWidget(self.add_files_button)
        root.addLayout(source_row)

        self.file_list = QListWidget()
        self.file_list.setMinimumHeight(62)
        self.file_list.currentRowChanged.connect(self._update_queue_buttons)
        root.addWidget(self.file_list)

        queue_actions = QHBoxLayout()
        self.remove_button = QPushButton("削除")
        self.remove_button.clicked.connect(self._remove_selected)
        self.move_up_button = QPushButton("上へ")
        self.move_up_button.clicked.connect(lambda: self._move_selected(-1))
        self.move_down_button = QPushButton("下へ")
        self.move_down_button.clicked.connect(lambda: self._move_selected(1))
        queue_actions.addWidget(self.remove_button)
        queue_actions.addWidget(self.move_up_button)
        queue_actions.addWidget(self.move_down_button)
        queue_actions.addStretch()
        root.addLayout(queue_actions)

        output_row = QHBoxLayout()
        output_row.addWidget(QLabel("保存先"))
        self.output_edit = QLineEdit()
        self.output_edit.setText(self._saved_output_dir())
        self.output_edit.editingFinished.connect(self._save_output_dir)
        self.output_edit.textChanged.connect(self._refresh_queue_display)
        output_row.addWidget(self.output_edit, 1)
        output_button = QPushButton("参照")
        output_button.clicked.connect(self._choose_output_dir)
        output_row.addWidget(output_button)
        self.open_output_button = QPushButton("保存先を開く")
        self.open_output_button.clicked.connect(self._open_output_dir)
        output_row.addWidget(self.open_output_button)
        root.addLayout(output_row)

        settings_row = QHBoxLayout()
        settings_row.addWidget(QLabel("出力"))
        self.txt_check = QCheckBox("TXT")
        self.json_check = QCheckBox("JSON")
        self.txt_check.setChecked(True)
        self.txt_check.toggled.connect(self._refresh_queue_display)
        self.json_check.toggled.connect(self._refresh_queue_display)
        settings_row.addWidget(self.txt_check)
        settings_row.addWidget(self.json_check)
        self.summary_check = QCheckBox("要約を先頭に追加")
        self.summary_check.setChecked(True)
        settings_row.addWidget(self.summary_check)
        settings_row.addSpacing(24)
        settings_row.addWidget(QLabel("モデル"))
        self.model_combo = QComboBox()
        self.model_combo.addItems(["tiny", "base", "small", "medium"])
        self.model_combo.setCurrentText("small")
        self.model_combo.currentTextChanged.connect(self._update_model_status)
        self.model_combo.currentTextChanged.connect(self._refresh_queue_display)
        settings_row.addWidget(self.model_combo)
        settings_row.addStretch()
        root.addLayout(settings_row)

        self.active_file_label = QLabel("処理対象: なし")
        self.active_file_label.setObjectName("activeFile")
        self.timing_label = QLabel("サイズ: - / 予測: - / 経過: -")
        self.timing_label.setObjectName("timing")
        self.status_label = QLabel("MP4ファイルを選択してください")
        root.addWidget(self.active_file_label)
        root.addWidget(self.timing_label)
        root.addWidget(self.status_label)

        model_row = QHBoxLayout()
        self.model_status_label = QLabel()
        self.model_status_label.setObjectName("modelStatus")
        model_row.addWidget(self.model_status_label, 1)
        self.delete_model_button = QPushButton("選択モデルを削除")
        self.delete_model_button.clicked.connect(self._delete_selected_model)
        model_row.addWidget(self.delete_model_button)
        self.delete_app_data_button = QPushButton("アプリ情報を削除")
        self.delete_app_data_button.clicked.connect(self._delete_app_data)
        model_row.addWidget(self.delete_app_data_button)
        root.addLayout(model_row)

        debug_header = QHBoxLayout()
        debug_header.addWidget(QLabel("デバッグ情報"))
        debug_header.addStretch()
        copy_debug_button = QPushButton("コピー")
        copy_debug_button.clicked.connect(self._copy_debug_info)
        debug_header.addWidget(copy_debug_button)
        root.addLayout(debug_header)
        self.debug_output = QPlainTextEdit()
        self.debug_output.setReadOnly(True)
        self.debug_output.setFixedHeight(54)
        self.debug_output.setPlaceholderText("エラーの詳細がここに表示されます")
        self.debug_output.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        root.addWidget(self.debug_output)

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

    def _choose_source(self) -> None:
        file_names, _ = QFileDialog.getOpenFileNames(self, "MP4を選択", "", "MP4 (*.mp4)")
        if file_names:
            self._add_sources(tuple(Path(file_name) for file_name in file_names))

    def _select_source(self, source: Path) -> None:
        self._add_sources((source,))

    def _add_sources(self, sources: tuple[Path, ...]) -> None:
        for source in sources:
            if source not in self._sources:
                self._sources.append(source)
                self._states.append(QueueState.PENDING)
                self.file_list.addItem(self._queue_text(source, QueueState.PENDING))
        self.drop_area.label.setText(f"{len(self._sources)} ファイルを選択中")
        self.status_label.setText("準備完了")
        self.start_button.setEnabled(bool(self._sources))
        self._update_queue_buttons()

    def _remove_selected(self) -> None:
        row = self.file_list.currentRow()
        if not self._is_pending(row):
            return
        source = self._sources[row]
        if self._worker is not None and not self._worker.remove_pending(source):
            return
        self.file_list.takeItem(row)
        self._sources.pop(row)
        self._states.pop(row)
        self.drop_area.label.setText(f"{len(self._sources)} ファイルを選択中")
        self.start_button.setEnabled(self._has_pending())
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
        self.remove_button.setEnabled(pending)
        self.move_up_button.setEnabled(pending and self._is_pending(row - 1))
        self.move_down_button.setEnabled(pending and self._is_pending(row + 1))

    def _choose_output_dir(self) -> None:
        directory = QFileDialog.getExistingDirectory(self, "保存先を選択")
        if directory:
            self.output_edit.setText(directory)
            self._save_output_dir()

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

        output_dir = Path(self.output_edit.text()) if self.output_edit.text() else None
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
            self.summary_check.isChecked(),
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
        self.drop_area.setEnabled(not running)
        self.file_list.setEnabled(True)
        self.model_combo.setEnabled(not running)
        self.delete_model_button.setEnabled(not running)
        self.delete_app_data_button.setEnabled(not running)
        self.exit_button.setEnabled(not running)
        for checkbox in (self.txt_check, self.json_check, self.summary_check):
            checkbox.setEnabled(not running)
        self._update_queue_buttons()

    def _on_file_started(self, source: Path, index: int, total: int, file_size: int) -> None:
        row = self._sources.index(source)
        self._states[row] = QueueState.ACTIVE
        self.file_list.setCurrentRow(row)
        self.file_list.item(row).setText(self._queue_text(source, QueueState.ACTIVE))
        self.active_file_label.setText(f"処理中: {source.name} ({index}/{total})")
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
            self.model_status_label.setText(
                f"モデル: {self.model_combo.currentText()} / {model_state}"
            )
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
        self.active_file_label.setText("処理対象: なし")
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
        self.active_file_label.setText("処理対象: なし")

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

    def _update_model_status(self) -> None:
        model_name = self.model_combo.currentText()
        try:
            status = inspect_model_cache(model_name)
        except Exception:
            self.model_status_label.setText(f"モデル: {model_name} / 状態確認エラー")
            self.delete_model_button.setEnabled(False)
            self._append_debug(f"モデル状態の確認に失敗しました\n{traceback.format_exc()}")
            return
        if status.downloaded:
            text = f"モデル: {model_name} / ダウンロード済み ({format_size(status.size_bytes)})"
        else:
            text = f"モデル: {model_name} / 未ダウンロード"
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

    def _queue_text(self, source: Path, state: QueueState) -> str:
        prediction = self._prediction_text(source)
        if self._is_transcribed(source):
            return f"[{state.value} / 文字起こし済み] {source.name} / 予測: {prediction}"
        return f"[{state.value}] {source.name} / 予測: {prediction}"

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
        output_dir = Path(self.output_edit.text().strip())
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

    def _copy_debug_info(self) -> None:
        QApplication.clipboard().setText(self.debug_output.toPlainText())

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
QFrame#dropArea {
    background: #ffffff;
    border: 2px dashed #7c9183;
    border-radius: 6px;
}
QLabel#dropTitle { font-size: 14px; font-weight: 600; background: transparent; }
QPushButton, QLineEdit, QComboBox {
    min-height: 24px;
    border: 1px solid #aab6ae;
    border-radius: 4px;
    background: #ffffff;
    padding: 0 10px;
}
QPushButton:hover { border-color: #276b49; }
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
"""
