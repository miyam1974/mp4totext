import os
import time
import traceback
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QSettings, QStandardPaths, Qt, QThread, QTimer
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QFileDialog, QMainWindow, QMessageBox

from mp4totext.application import OutputFormat, TranscriptionResult
from mp4totext.application.output_plan import (
    find_output_collision,
    output_directory,
    output_paths_for,
)
from mp4totext.application.queue import QueueState, TranscriptionQueue
from mp4totext.domain import ProgressEvent, ProgressStage, TranscriptionOptions
from mp4totext.engine.model_cache import (
    delete_app_cache,
    delete_model_cache,
    format_size,
    inspect_model_cache,
)
from mp4totext.gui.i18n import Language, Translator, set_qt_language
from mp4totext.gui.job_controller import TranscriptionWorker
from mp4totext.gui.main_view import MainView
from mp4totext.gui.processing_history import (
    ProcessingMetrics,
    append_history,
    estimate_seconds,
    format_duration,
    load_history,
)
from mp4totext.gui.styles import STYLESHEET

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
        self._queue = TranscriptionQueue()
        self._cancel_requested = False
        self._batch_counts = (0, 0)
        self._run_settings: (
            tuple[Path | None, tuple[OutputFormat, ...], TranscriptionOptions] | None
        ) = None
        self._thread: QThread | None = None
        self._worker: TranscriptionWorker | None = None
        self._model_refresh_pending = False
        self._model_downloaded = False
        self._running = False
        self.ui = MainView(
            self._i18n,
            bool(self._settings.value("output/same_folder", False, type=bool)),
            self._saved_output_dir(),
        )
        self.setCentralWidget(self.ui)
        self.setStyleSheet(STYLESHEET)
        self._connect_ui()
        self._update_output_mode()
        self._set_status("select_mp4_prompt")
        self._set_active_file("none")
        self._retranslate()

    def t(self, key: str, **kwargs: object) -> str:
        return self._i18n.t(key, **kwargs)

    @property
    def _sources(self) -> list[Path]:
        return [item.source for item in self._queue.snapshot()]

    @property
    def _states(self) -> list[QueueState]:
        return [item.state for item in self._queue.snapshot()]

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
        self.ui.retranslate()
        self.setWindowTitle(self.t("window_title"))
        if self._status_state is not None:
            key, kwargs = self._status_state
            self.ui.status_label.setText(self.t(key, **kwargs))
        if self._active_file_state is not None:
            key, kwargs = self._active_file_state
            self.ui.active_file_label.setText(self.t(key, **kwargs))
        self._update_elapsed_time()
        self.ui.cancel_button.setText(
            self.t("cancel_model_download") if self._model_refresh_pending else self.t("cancel")
        )
        self._update_model_status()
        self._update_model_description()
        self._refresh_queue_display()

    def _set_status(self, key: str, **kwargs: object) -> None:
        self._status_state = (key, kwargs)
        self.ui.status_label.setText(self.t(key, **kwargs))

    def _set_active_file(self, key: str, **kwargs: object) -> None:
        self._active_file_state = (key, kwargs)
        self.ui.active_file_label.setText(self.t(key, **kwargs))

    def _connect_ui(self) -> None:
        self.ui.lang_ja_button.toggled.connect(self._on_ja_toggled)
        self.ui.lang_en_button.toggled.connect(self._on_en_toggled)
        self.ui.file_list.files_dropped.connect(self._add_sources)
        self.ui.file_list.currentRowChanged.connect(self._update_queue_buttons)
        self.ui.add_files_button.clicked.connect(self._choose_source)
        self.ui.remove_button.clicked.connect(self._remove_selected)
        self.ui.move_up_button.clicked.connect(lambda: self._move_selected(-1))
        self.ui.move_down_button.clicked.connect(lambda: self._move_selected(1))
        self.ui.open_source_folder_button.clicked.connect(self._open_source_folder)
        self.ui.same_folder_radio.toggled.connect(self._update_output_mode)
        self.ui.output_edit.editingFinished.connect(self._save_output_dir)
        self.ui.output_edit.textChanged.connect(self._refresh_queue_display)
        self.ui.output_browse_button.clicked.connect(self._choose_output_dir)
        self.ui.open_output_button.clicked.connect(self._open_output_dir)
        self.ui.txt_check.toggled.connect(self._refresh_queue_display)
        self.ui.json_check.toggled.connect(self._refresh_queue_display)
        self.ui.model_combo.currentTextChanged.connect(self._update_model_status)
        self.ui.model_combo.currentTextChanged.connect(self._update_model_description)
        self.ui.model_combo.currentTextChanged.connect(self._refresh_queue_display)
        self.ui.delete_model_button.clicked.connect(self._delete_selected_model)
        self.ui.delete_app_data_button.clicked.connect(self._delete_app_data)
        self.ui.cancel_button.clicked.connect(self._cancel)
        self.ui.exit_button.clicked.connect(self.close)
        self.ui.start_button.clicked.connect(self._start)

    def _choose_source(self) -> None:
        file_names, _ = QFileDialog.getOpenFileNames(
            self, self.t("select_mp4_dialog_title"), "", "MP4 (*.mp4)",
            options=QFileDialog.Option.DontUseNativeDialog,
        )
        if file_names:
            self._add_sources(tuple(Path(file_name) for file_name in file_names))

    def _add_sources(self, sources: tuple[Path, ...]) -> None:
        if self._worker is not None:
            collision = find_output_collision(
                (*self._sources, *sources), self._selected_formats(), self._output_dir(),
            )
            if collision is not None:
                QMessageBox.warning(
                    self, self.t("destination_title"), self.t("output_collision", path=collision),
                )
                return
        self._queue.add(sources)
        self._refresh_queue_display()
        self._set_status("files_selected", count=len(self._sources))
        self._update_queue_buttons()

    def _remove_selected(self) -> None:
        row = self.ui.file_list.currentRow()
        if not self._is_removable(row):
            return
        source = self._sources[row]
        if not self._queue.remove(source):
            self._refresh_queue_display()
            return
        self._refresh_queue_display()
        self._set_status("files_selected", count=len(self._sources))
        self._update_queue_buttons()

    def _move_selected(self, offset: int) -> None:
        row = self.ui.file_list.currentRow()
        destination = row + offset
        if not self._is_pending(row) or not self._is_pending(destination):
            return
        self._queue.move(self._sources[row], offset)
        self._refresh_queue_display()

    def _update_queue_buttons(self) -> None:
        row = self.ui.file_list.currentRow()
        pending = self._is_pending(row)
        self.ui.remove_button.setEnabled(self._is_removable(row))
        self.ui.move_up_button.setEnabled(pending and self._is_pending(row - 1))
        self.ui.move_down_button.setEnabled(pending and self._is_pending(row + 1))
        self.ui.open_source_folder_button.setEnabled(0 <= row < len(self._sources))
        self._update_controls()

    def _open_source_folder(self) -> None:
        row = self.ui.file_list.currentRow()
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
            self.ui.output_edit.setText(directory)
            self._save_output_dir()

    def _update_output_mode(self) -> None:
        same_folder = self.ui.same_folder_radio.isChecked()
        self._settings.setValue("output/same_folder", same_folder)
        self._refresh_queue_display()

    def _open_output_dir(self) -> None:
        if not self.ui.output_edit.text().strip():
            QMessageBox.warning(
                self, self.t("destination_title"), self.t("destination_required"),
            )
            return
        directory = Path(self.ui.output_edit.text().strip())
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
            (self.ui.txt_check, OutputFormat.TXT),
            (self.ui.json_check, OutputFormat.JSON),
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

        output_dir = self._output_dir()
        collision = find_output_collision(pending_sources, formats, output_dir)
        if collision is not None:
            QMessageBox.warning(
                self, self.t("destination_title"), self.t("output_collision", path=collision),
            )
            return
        existing = [
            path
            for source in pending_sources
            for path in output_paths_for(source, formats, output_dir)
        ]
        overwrite = any(path.exists() for path in existing)
        if overwrite and QMessageBox.question(
            self,
            self.t("overwrite_confirm_title"),
            self.t("overwrite_confirm_message"),
        ) != QMessageBox.StandardButton.Yes:
            return

        self._cancel_requested = False
        self._batch_counts = (0, 0)
        self._run_settings = (
            output_dir, formats, TranscriptionOptions(model_name=self.ui.model_combo.currentText()),
        )
        self._launch_worker(pending_sources, overwrite)

    def _launch_worker(self, sources: tuple[Path, ...], overwrite: bool) -> None:
        assert self._run_settings is not None
        output_dir, formats, options = self._run_settings
        self._set_running(True)
        self._thread = QThread(self)
        self._worker = TranscriptionWorker(
            sources,
            output_dir,
            formats,
            options,
            overwrite,
            queue=self._queue,
        )
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.file_started.connect(self._on_file_started)
        self._worker.progress.connect(self._on_progress)
        self._worker.file_completed.connect(self._on_file_completed)
        self._worker.file_failed.connect(self._on_file_failed)
        self._worker.batch_completed.connect(self._on_batch_completed)
        self._worker.cancelled.connect(self._on_cancelled)
        self._worker.fatal_error.connect(self._on_worker_error)
        self._worker.finished.connect(self._thread.quit)
        self._worker.finished.connect(self._worker.deleteLater)
        self._thread.finished.connect(self._job_finished)
        self._thread.finished.connect(self._thread.deleteLater)
        self._thread.start()

    def _set_running(self, running: bool) -> None:
        self._running = running
        self._update_queue_buttons()

    def _update_controls(self) -> None:
        self.ui.update_controls(
            running=self._running or self._thread is not None,
            has_pending=self._has_pending(),
            cancelling=self._cancel_requested,
            model_downloaded=self._model_downloaded,
        )
        self.ui.cancel_button.setText(
            self.t("cancel_model_download") if self._model_refresh_pending else self.t("cancel")
        )

    def _on_file_started(self, source: Path, index: int, total: int, file_size: int) -> None:
        if source not in self._sources:
            return
        row = self._sources.index(source)
        if self._worker is None:
            self._queue.set_state(source, QueueState.ACTIVE)
        self._refresh_queue_display()
        self.ui.file_list.setCurrentRow(row)
        self._set_active_file("active_file_progress", name=source.name, index=index, total=total)
        self._active_file_size = file_size
        self._estimated_seconds = estimate_seconds(
            self.ui.model_combo.currentText(),
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
            self.ui.status_label.setText(event.message)
        if event.stage is ProgressStage.DOWNLOADING_MODEL:
            self._model_refresh_pending = True
            self._download_fraction = event.fraction
            self._update_model_status()
        elif event.stage is ProgressStage.TRANSCRIBING and self._model_refresh_pending:
            self._model_refresh_pending = False
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
        if source not in self._sources:
            return
        row = self._sources.index(source)
        if self._worker is None:
            self._queue.set_state(source, QueueState.COMPLETED)
        self.ui.file_list.item(row).setToolTip("\n".join(str(path) for path in result.output_paths))
        self._refresh_queue_display()

    def _on_file_failed(self, source: Path, message: str) -> None:
        self._finish_timing()
        self._append_debug(f"{source}\n{message}")
        if source not in self._sources:
            return
        row = self._sources.index(source)
        if self._worker is None:
            self._queue.set_state(source, QueueState.FAILED)
        self.ui.file_list.item(row).setToolTip(message)
        self._refresh_queue_display()

    def _on_batch_completed(self, completed: int, failed: int) -> None:
        previous_completed, previous_failed = self._batch_counts
        self._batch_counts = (previous_completed + completed, previous_failed + failed)

    def _show_batch_completed(self) -> None:
        completed, failed = self._batch_counts
        self._set_active_file("none")
        self._set_status("batch_completed_status", completed=completed, failed=failed)
        QMessageBox.information(
            self,
            self.t("batch_completed_title"),
            self.t("batch_completed_message", completed=completed, failed=failed),
        )

    def _on_cancelled(self) -> None:
        self._cancel_requested = True
        self._finish_timing()
        self._model_refresh_pending = False
        self._set_status("cancelled_status")
        self._set_active_file("none")
        for item in self._queue.snapshot():
            if item.state is QueueState.ACTIVE:
                self._queue.set_state(item.source, QueueState.PENDING)
        self._refresh_queue_display()

    def _cancel(self) -> None:
        if self._worker is not None:
            self._cancel_requested = True
            self._set_status("cancelling_status")
            self._update_controls()
            self._worker.cancel()

    def _on_worker_error(self, message: str) -> None:
        self._on_cancelled()
        self._set_status("queue_failed")
        self._append_debug(message)

    def _job_finished(self) -> None:
        self._thread = None
        self._worker = None
        self._model_refresh_pending = False
        self._refresh_queue_display()
        if (
            self._cancel_requested
            and self._status_state is not None
            and self._status_state[0] == "cancelling_status"
        ):
            self._on_cancelled()
        if self._run_settings is not None and not self._cancel_requested and self._has_pending():
            self._launch_worker(self._pending_sources(), False)
            return
        self._set_running(False)
        self._update_model_status()
        if self._run_settings is not None and not self._cancel_requested:
            self._show_batch_completed()
        self._run_settings = None

    def _update_elapsed_time(self) -> None:
        if self._timing_started_at is None and self._finished_elapsed is None:
            self.ui.timing_label.setText(self.t("timing_placeholder"))
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
        self.ui.timing_label.setText(
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
        key = _MODEL_DESCRIPTION_KEYS.get(self.ui.model_combo.currentText())
        self.ui.model_description_label.setText(self.t(key) if key is not None else "")

    def _update_model_status(self) -> None:
        model_name = self.ui.model_combo.currentText()
        if self._model_refresh_pending:
            state = (
                self.t("preparing")
                if self._download_fraction is None
                else self.t("downloading", percent=f"{self._download_fraction:.0%}")
            )
            self.ui.model_status_label.setText(f"{model_name} / {state}")
            self._update_controls()
            return
        try:
            status = inspect_model_cache(model_name)
        except Exception:
            self.ui.model_status_label.setText(f"{model_name} / {self.t('status_check_error')}")
            self._model_downloaded = False
            self._update_controls()
            self._append_debug(f"{self.t('model_status_failed_debug')}\n{traceback.format_exc()}")
            return
        if status.downloaded:
            text = f"{model_name} / {self.t('downloaded', size=format_size(status.size_bytes))}"
        else:
            text = f"{model_name} / {self.t('not_downloaded')}"
        self.ui.model_status_label.setText(text)
        self._model_downloaded = status.downloaded
        self._update_controls()

    def _delete_selected_model(self) -> None:
        model_name = self.ui.model_combo.currentText()
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
        self.ui.output_edit.setText(self._default_output_dir())
        self._save_output_dir()
        self._update_model_status()

    def _has_pending(self) -> bool:
        return QueueState.PENDING in self._states

    def _pending_sources(self) -> tuple[Path, ...]:
        return self._queue.pending()

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
            self.ui.model_combo.currentText(),
            file_size,
            load_history(self._settings),
        )
        return (
            format_duration(predicted, self._i18n.language)
            if predicted is not None else self.t("history_none")
        )

    def _refresh_queue_display(self) -> None:
        selected = self.ui.file_list.currentItem()
        selected_source = selected.data(Qt.ItemDataRole.UserRole) if selected is not None else None
        tooltips = {
            item.data(Qt.ItemDataRole.UserRole): item.toolTip()
            for row in range(self.ui.file_list.count())
            if (item := self.ui.file_list.item(row)) is not None
        }
        self.ui.file_list.blockSignals(True)
        self.ui.file_list.clear()
        for entry in self._queue.snapshot():
            self.ui.file_list.addItem(self._queue_text(entry.source, entry.state))
            item = self.ui.file_list.item(self.ui.file_list.count() - 1)
            item.setData(Qt.ItemDataRole.UserRole, entry.source)
            item.setToolTip(tooltips.get(entry.source, ""))
            if entry.source == selected_source:
                self.ui.file_list.setCurrentItem(item)
        self.ui.file_list.blockSignals(False)
        self._update_queue_buttons()

    def _is_transcribed(self, source: Path) -> bool:
        formats = self._selected_formats()
        if not formats:
            return False
        return all(path.is_file() for path in output_paths_for(source, formats, self._output_dir()))

    def _output_dir(self) -> Path | None:
        return output_directory(self.ui.same_folder_radio.isChecked(), self.ui.output_edit.text())

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
        directory = self.ui.output_edit.text().strip()
        if directory:
            self._settings.setValue("output/directory", directory)

    def _append_debug(self, details: str) -> None:
        if self.ui.debug_output.toPlainText():
            self.ui.debug_output.appendPlainText("\n" + "-" * 60)
        self.ui.debug_output.appendPlainText(details.rstrip())
        scroll_bar = self.ui.debug_output.verticalScrollBar()
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
