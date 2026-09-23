import os
from pathlib import Path
from threading import Event
from typing import Any, cast

import pytest
from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import QFileDialog, QMessageBox
from pytestqt.qtbot import QtBot

from mp4totext.application import OutputFormat, TranscriptionResult
from mp4totext.application.queue import QueueState
from mp4totext.domain import ProgressEvent, ProgressStage, TranscriptionOptions
from mp4totext.domain.processing_history import ProcessingMetrics
from mp4totext.engine.model_cache import ModelCacheStatus
from mp4totext.gui import job_controller, main_window
from mp4totext.gui.history_store import append_history, load_history
from mp4totext.gui.job_controller import TranscriptionWorker
from mp4totext.gui.main_window import MainWindow


def test_window_accepts_a_selected_mp4(qtbot: QtBot) -> None:
    window = MainWindow()
    qtbot.addWidget(window)

    window._add_sources((Path("meeting.mp4"), Path("review.mp4")))

    assert window.ui.start_button.isEnabled()
    assert window.ui.status_label.text() == "2 ファイルを選択中"
    assert window.ui.file_list.count() == 2
    assert window._selected_formats() == (OutputFormat.TXT,)
    assert window.ui.file_list.item(0).text().endswith("/ 予測: 算出不可")


def test_sources_can_be_added_while_transcription_is_running(qtbot: QtBot) -> None:
    window = MainWindow()
    qtbot.addWidget(window)
    window._add_sources((Path("meeting.mp4"),))
    window._set_running(True)
    cast(Any, window)._thread = object()

    assert window.ui.file_list.isEnabled()

    window._add_sources((Path("review.mp4"),))

    assert window.ui.file_list.count() == 2
    assert not window.ui.start_button.isEnabled()

    cast(Any, window)._thread = None


def test_window_requires_at_least_one_output_format(qtbot: QtBot) -> None:
    window = MainWindow()
    qtbot.addWidget(window)

    window.ui.txt_check.setChecked(False)

    assert window._selected_formats() == ()


def test_window_shows_active_file(qtbot: QtBot) -> None:
    window = MainWindow()
    qtbot.addWidget(window)
    source = Path("review.mp4")
    window._add_sources((Path("meeting.mp4"), source))

    window._on_file_started(source, 2, 2, 2048)

    assert window.ui.file_list.currentRow() == 1
    assert window.ui.file_list.item(1).text() == "[処理中] review.mp4 (算出不可) / 予測: 算出不可"
    assert window.ui.active_file_label.text() == "review.mp4 (2/2)"
    assert window.ui.timing_label.text().startswith("サイズ: 2.0 KiB / 予測: ")
    assert window.ui.timing_label.text().endswith("/ 経過: 0秒")


def test_pending_files_can_be_reordered_and_removed(qtbot: QtBot) -> None:
    window = MainWindow()
    qtbot.addWidget(window)
    window._add_sources((Path("first.mp4"), Path("second.mp4")))

    window.ui.file_list.setCurrentRow(1)
    window._move_selected(-1)
    window._remove_selected()

    assert window._sources == [Path("first.mp4")]


def test_completed_or_failed_files_can_be_removed(qtbot: QtBot) -> None:
    window = MainWindow()
    qtbot.addWidget(window)
    window._add_sources((Path("done.mp4"), Path("failed.mp4")))
    window._queue.set_state(window._sources[0], QueueState.COMPLETED)
    window._queue.set_state(window._sources[1], QueueState.FAILED)

    window.ui.file_list.setCurrentRow(0)
    window._remove_selected()
    window.ui.file_list.setCurrentRow(0)
    window._remove_selected()

    assert window._sources == []


def test_active_file_cannot_be_removed(qtbot: QtBot) -> None:
    window = MainWindow()
    qtbot.addWidget(window)
    window._add_sources((Path("processing.mp4"),))
    window._queue.set_state(window._sources[0], QueueState.ACTIVE)
    window.ui.file_list.setCurrentRow(0)

    window._remove_selected()

    assert window._sources == [Path("processing.mp4")]


def test_pending_file_can_be_removed_while_running(qtbot: QtBot) -> None:
    window = MainWindow()
    qtbot.addWidget(window)
    window._add_sources((Path("first.mp4"), Path("second.mp4")))
    window._set_running(True)
    window._on_file_started(Path("first.mp4"), 1, 2, 0)
    window._worker = TranscriptionWorker(
        (Path("second.mp4"),),
        None,
        (OutputFormat.TXT,),
        TranscriptionOptions(),
        False,
        queue=window._queue,
    )
    window.ui.file_list.setCurrentRow(1)

    window._remove_selected()

    assert window._sources == [Path("first.mp4")]
    assert not window.ui.start_button.isEnabled()


def test_file_added_while_running_is_registered_with_the_worker(qtbot: QtBot) -> None:
    window = MainWindow()
    qtbot.addWidget(window)
    window._add_sources((Path("first.mp4"),))
    window._set_running(True)
    window._on_file_started(Path("first.mp4"), 1, 1, 0)
    window._worker = TranscriptionWorker(
        (),
        None,
        (OutputFormat.TXT,),
        TranscriptionOptions(),
        False,
        queue=window._queue,
    )

    window._add_sources((Path("added_mid_run.mp4"),))

    assert window._worker.queue.pending() == (Path("added_mid_run.mp4"),)

    window.ui.file_list.setCurrentRow(1)
    window._remove_selected()

    assert window._sources == [Path("first.mp4")]


def test_model_dropdown_shows_download_status(
    qtbot: QtBot,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        main_window,
        "inspect_model_cache",
        lambda name: ModelCacheStatus(name, name == "small", 486_212_372),
    )
    window = MainWindow()
    qtbot.addWidget(window)

    assert window.ui.model_status_label.text() == "small / ダウンロード済み (463.7 MiB)"
    window.ui.model_combo.setCurrentText("tiny")
    assert window.ui.model_status_label.text() == "tiny / 未ダウンロード"


def test_model_dropdown_shows_a_short_description(qtbot: QtBot) -> None:
    window = MainWindow()
    qtbot.addWidget(window)

    assert window.ui.model_description_label.text() == "既定値。速度と精度のバランスを優先"
    window.ui.model_combo.setCurrentText("tiny")
    assert window.ui.model_description_label.text() == "最も軽量・高速"


def test_debug_output_is_scrollable_and_selectable(qtbot: QtBot) -> None:
    window = MainWindow()
    qtbot.addWidget(window)
    source = Path("failed.mp4")
    window._add_sources((source,))
    details = "Traceback\n" + "\n".join(f"line {index}" for index in range(50))

    window._on_file_failed(source, details)

    assert "Traceback" in window.ui.debug_output.toPlainText()
    assert window.ui.debug_output.verticalScrollBar().maximum() > 0
    assert (
        window.ui.debug_output.textInteractionFlags()
        & Qt.TextInteractionFlag.TextSelectableByMouse
    )


def test_debug_output_is_always_visible(qtbot: QtBot) -> None:
    window = MainWindow()
    qtbot.addWidget(window)

    assert not window.ui.debug_output.isHidden()


def test_model_download_updates_status_and_keeps_cancel_enabled(
    qtbot: QtBot,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    downloaded = False

    def cache_status(name: str) -> ModelCacheStatus:
        return ModelCacheStatus(name, downloaded, 1024 if downloaded else 0)

    monkeypatch.setattr(main_window, "inspect_model_cache", cache_status)
    window = MainWindow()
    qtbot.addWidget(window)
    window._set_running(True)

    window._on_progress(
        ProgressEvent(ProgressStage.DOWNLOADING_MODEL, 0.4, "Downloading bytes")
    )

    assert window.ui.model_status_label.text() == "small / ダウンロード中 (40%)"
    assert window.ui.cancel_button.isEnabled()
    assert window.ui.cancel_button.text() == "モデル取得をキャンセル"

    downloaded = True
    window._on_progress(ProgressEvent(ProgressStage.TRANSCRIBING, 0.0, "文字起こし中"))

    assert window.ui.model_status_label.text() == "small / ダウンロード済み (1.0 KiB)"
    assert window.ui.cancel_button.text() == "キャンセル"


def test_cancelling_active_file_allows_restarting_the_queue(qtbot: QtBot) -> None:
    window = MainWindow()
    qtbot.addWidget(window)
    source = Path("meeting.mp4")
    window._add_sources((source,))
    window._on_file_started(source, 1, 1, 0)

    window._on_cancelled()
    window._job_finished()

    assert window._states == [QueueState.PENDING]
    assert window.ui.file_list.item(0).text().startswith("[待機]")
    assert window.ui.start_button.isEnabled()


def test_window_uses_requested_initial_height(qtbot: QtBot) -> None:
    window = MainWindow()
    qtbot.addWidget(window)

    assert window.height() == 560


def test_language_toggle_switches_ui_text_and_persists(
    qtbot: QtBot,
    tmp_path: Path,
) -> None:
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    window = MainWindow(settings)
    qtbot.addWidget(window)
    window._add_sources((Path("meeting.mp4"),))

    assert window.ui.lang_ja_button.isChecked()
    assert window.ui.add_files_button.text() == "MP4を追加"
    assert window.ui.file_list.item(0).text().startswith("[待機]")

    window.ui.lang_en_button.setChecked(True)

    assert window.ui.add_files_button.text() == "Add MP4"
    assert window.ui.remove_button.text() == "Remove"
    assert window.ui.same_folder_radio.text() == "Same folder as video"
    assert window.ui.file_list.item(0).text().startswith("[Pending]")
    assert settings.value("app/language", type=str) == "en"

    second_window = MainWindow(settings)
    qtbot.addWidget(second_window)

    assert second_window.ui.lang_en_button.isChecked()
    assert second_window.ui.add_files_button.text() == "Add MP4"


def test_language_toggle_updates_dynamic_status_text(qtbot: QtBot) -> None:
    window = MainWindow()
    qtbot.addWidget(window)
    source = Path("meeting.mp4")
    window._add_sources((source,))
    window._on_file_started(source, 1, 1, 0)

    window._on_progress(ProgressEvent(ProgressStage.TRANSCRIBING, 0.2, "文字起こし中"))
    assert window.ui.status_label.text() == "文字起こし中"

    window.ui.lang_en_button.setChecked(True)

    assert window.ui.active_file_label.text() == "meeting.mp4 (1/1)"
    assert window.ui.timing_label.text().startswith("Size: ")
    assert window.ui.status_label.text() == "Transcribing"
    assert window.ui.timing_label.text().endswith("Elapsed: 0s")

    window.ui.lang_ja_button.setChecked(True)
    assert window.ui.status_label.text() == "文字起こし中"
    assert window.ui.add_files_button.text() == "MP4を追加"
    assert window._settings.value("app/language") == "ja"


def test_open_output_directory_uses_selected_destination(
    qtbot: QtBot,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    opened: list[Path] = []
    monkeypatch.setattr(os, "startfile", lambda path: opened.append(Path(path)))
    window = MainWindow()
    qtbot.addWidget(window)
    window.ui.output_edit.setText(str(tmp_path))

    window._open_output_dir()

    assert opened == [tmp_path.resolve()]


def test_open_source_folder_opens_the_selected_videos_directory(
    qtbot: QtBot,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    opened: list[Path] = []
    monkeypatch.setattr(os, "startfile", lambda path: opened.append(Path(path)))
    source = tmp_path / "meeting.mp4"
    source.touch()
    window = MainWindow()
    qtbot.addWidget(window)
    window._add_sources((source,))
    window.ui.file_list.setCurrentRow(0)

    assert window.ui.open_source_folder_button.isEnabled()
    window._open_source_folder()

    assert opened == [tmp_path.resolve()]


def test_output_directory_persists_across_windows(
    qtbot: QtBot,
    tmp_path: Path,
) -> None:
    settings_path = tmp_path / "settings.ini"
    first_settings = QSettings(str(settings_path), QSettings.Format.IniFormat)
    first_window = MainWindow(first_settings)
    qtbot.addWidget(first_window)
    output_dir = tmp_path / "outputs"
    first_window.ui.output_edit.setText(str(output_dir))
    first_window._save_output_dir()
    first_settings.sync()

    second_settings = QSettings(str(settings_path), QSettings.Format.IniFormat)
    second_window = MainWindow(second_settings)
    qtbot.addWidget(second_window)

    assert second_window.ui.output_edit.text() == str(output_dir)


def test_output_mode_toggle_enables_correct_controls_and_persists(
    qtbot: QtBot,
    tmp_path: Path,
) -> None:
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    window = MainWindow(settings)
    qtbot.addWidget(window)

    assert window.ui.custom_folder_radio.isChecked()
    assert window.ui.output_edit.isEnabled()
    assert window.ui.output_browse_button.isEnabled()
    assert window.ui.open_output_button.isEnabled()

    window.ui.same_folder_radio.setChecked(True)

    assert not window.ui.output_edit.isEnabled()
    assert not window.ui.output_browse_button.isEnabled()
    assert not window.ui.open_output_button.isEnabled()
    assert settings.value("output/same_folder", type=bool) is True


def test_same_folder_mode_uses_the_videos_own_directory(
    qtbot: QtBot,
    tmp_path: Path,
) -> None:
    source = tmp_path / "meeting.mp4"
    source.touch()
    (tmp_path / "meeting.txt").write_text("transcript", encoding="utf-8")
    window = MainWindow(
        QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    )
    qtbot.addWidget(window)
    window.ui.output_edit.setText(str(tmp_path / "elsewhere"))
    window.ui.same_folder_radio.setChecked(True)

    window._add_sources((source,))

    assert window.ui.file_list.item(0).text().startswith("[待機 / 文字起こし済み]")


def test_saved_output_directory_can_open_before_adding_video(
    qtbot: QtBot,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    settings.setValue("output/directory", str(tmp_path))
    opened: list[Path] = []
    monkeypatch.setattr(os, "startfile", lambda path: opened.append(Path(path)))
    window = MainWindow(settings)
    qtbot.addWidget(window)

    window._open_output_dir()

    assert opened == [tmp_path.resolve()]


def test_queue_marks_video_when_all_selected_outputs_exist(
    qtbot: QtBot,
    tmp_path: Path,
) -> None:
    source = tmp_path / "meeting.mp4"
    source.touch()
    (tmp_path / "meeting.txt").write_text("transcript", encoding="utf-8")
    window = MainWindow(
        QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    )
    qtbot.addWidget(window)
    window.ui.output_edit.setText(str(tmp_path))

    window._add_sources((source,))

    assert window.ui.file_list.item(0).text() == (
        "[待機 / 文字起こし済み] meeting.mp4 (0.0 MB) / 予測: 履歴なし"
    )

    window.ui.json_check.setChecked(True)
    assert window.ui.file_list.item(0).text() == "[待機] meeting.mp4 (0.0 MB) / 予測: 履歴なし"

    (tmp_path / "meeting.json").write_text("{}", encoding="utf-8")
    window._refresh_queue_display()
    assert window.ui.file_list.item(0).text() == (
        "[待機 / 文字起こし済み] meeting.mp4 (0.0 MB) / 予測: 履歴なし"
    )


def test_timing_uses_model_history_and_records_success(
    qtbot: QtBot,
    tmp_path: Path,
) -> None:
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    append_history(settings, ProcessingMetrics("small", 1000, 10.0))
    current_time = 100.0
    window = MainWindow(settings, clock=lambda: current_time)
    qtbot.addWidget(window)
    source = tmp_path / "meeting.mp4"
    source.write_bytes(b"x" * 2000)
    window._add_sources((source,))

    assert window.ui.file_list.item(0).text().endswith("/ 予測: 20秒")

    window._on_file_started(source, 1, 1, 2000)

    assert window.ui.timing_label.text() == "サイズ: 2.0 KiB / 予測: 20秒 / 経過: 0秒"

    result = TranscriptionResult((tmp_path / "meeting.txt",), "ja", 60.0)
    metrics = ProcessingMetrics("small", 2000, 25.0)
    window._on_file_completed(source, result, metrics)

    assert window.ui.timing_label.text() == "サイズ: 2.0 KiB / 予測: 20秒 / 経過: 25秒"
    assert load_history(settings)[-1] == metrics

    window.ui.lang_en_button.setChecked(True)
    assert window.ui.timing_label.text() == "Size: 2.0 KiB / Est: 20s / Elapsed: 25s"
    assert "Est: " in window.ui.file_list.item(0).text()
    assert "秒" not in window.ui.file_list.item(0).text()
    window.ui.lang_ja_button.setChecked(True)
    assert window.ui.timing_label.text() == "サイズ: 2.0 KiB / 予測: 20秒 / 経過: 25秒"


@pytest.mark.parametrize("fraction", [None, 0.4])
def test_language_switch_preserves_download_progress(qtbot: QtBot, fraction: float | None) -> None:
    window = MainWindow()
    qtbot.addWidget(window)
    window._on_progress(ProgressEvent(ProgressStage.DOWNLOADING_MODEL, fraction, "download"))
    japanese = window.ui.model_status_label.text()
    window.ui.lang_en_button.setChecked(True)
    state = "Preparing" if fraction is None else "Downloading (40%)"
    assert window.ui.model_status_label.text() == f"small / {state}"
    assert window.ui.cancel_button.text() == "Cancel model download"
    window.ui.lang_ja_button.setChecked(True)
    assert window.ui.model_status_label.text() == japanese


def test_error_dialog_is_localized_and_debug_keeps_original(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    window = MainWindow()
    qtbot.addWidget(window)
    window.ui.lang_en_button.setChecked(True)
    window.ui.output_edit.setText(str(tmp_path))
    messages: list[str] = []

    def fail_open(path: Path) -> None:
        raise OSError("アクセス拒否")

    monkeypatch.setattr(os, "startfile", fail_open)
    monkeypatch.setattr(
        QMessageBox, "critical",
        lambda parent, title, message: messages.append(message),
    )
    window._open_output_dir()
    assert messages == ["Could not open the destination\nSee the Debug panel for details."]
    assert "アクセス拒否" in window.ui.debug_output.toPlainText()


def test_file_dialogs_use_translatable_qt_widgets(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch,
) -> None:
    window = MainWindow()
    qtbot.addWidget(window)
    window.ui.lang_en_button.setChecked(True)
    calls: list[tuple[str, Any]] = []

    def files(parent: object, title: str, *args: Any, **kwargs: Any) -> tuple[list[str], str]:
        calls.append((title, kwargs["options"]))
        return [], ""

    def directory(parent: object, title: str, **kwargs: Any) -> str:
        calls.append((title, kwargs["options"]))
        return ""

    monkeypatch.setattr(QFileDialog, "getOpenFileNames", files)
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", directory)
    window._choose_source()
    window._choose_output_dir()
    assert [title for title, _ in calls] == ["Select MP4", "Select destination"]
    assert all(options & QFileDialog.Option.DontUseNativeDialog for _, options in calls)


def test_blank_destination_uses_source_folder_for_existing_output(
    qtbot: QtBot, tmp_path: Path,
) -> None:
    source = tmp_path / "meeting.mp4"
    source.with_suffix(".txt").write_text("existing", encoding="utf-8")
    window = MainWindow()
    qtbot.addWidget(window)
    window.ui.output_edit.setText("  ")
    assert window._output_dir() is None
    assert window._is_transcribed(source)


def test_start_rejects_output_collision_before_creating_worker(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    window = MainWindow()
    qtbot.addWidget(window)
    window.ui.output_edit.setText(str(tmp_path))
    window._add_sources((tmp_path / "a" / "meeting.mp4", tmp_path / "b" / "meeting.mp4"))
    messages: list[str] = []
    monkeypatch.setattr(
        QMessageBox, "warning", lambda parent, title, message: messages.append(message),
    )
    window._start()
    assert len(messages) == 1
    assert str(tmp_path / "meeting.txt") in messages[0]
    assert window._worker is None


@pytest.mark.parametrize("cancel", [False, True])
def test_late_addition_at_worker_shutdown_is_not_lost(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, cancel: bool,
) -> None:
    window = MainWindow()
    qtbot.addWidget(window)
    window.ui.output_edit.setText(str(tmp_path))
    first, late = tmp_path / "first.mp4", tmp_path / "late.mp4"
    window._add_sources((first,))
    empty_seen, release = Event(), Event()
    claim = window._queue.claim_next
    calls: list[Path] = []
    notifications: list[str] = []

    def pause_after_empty() -> Path | None:
        source = claim()
        if source is None and not empty_seen.is_set():
            empty_seen.set()
            assert release.wait(5), "GUI did not release worker"
        return source

    def transcribe(**kwargs: Any) -> TranscriptionResult:
        calls.append(kwargs["source"])
        return TranscriptionResult((kwargs["source"].with_suffix(".txt"),), "ja", 1.0)

    monkeypatch.setattr(window._queue, "claim_next", pause_after_empty)
    monkeypatch.setattr(job_controller, "FasterWhisperTranscriber", object)
    monkeypatch.setattr(job_controller, "transcribe_file", transcribe)
    monkeypatch.setattr(
        QMessageBox, "information", lambda parent, title, text: notifications.append(text),
    )
    try:
        window._start()
        qtbot.waitUntil(empty_seen.is_set)
        window._add_sources((late,))
        if cancel:
            window._cancel()
        release.set()
        qtbot.waitUntil(lambda: window._thread is None, timeout=5000)
        assert calls == ([first] if cancel else [first, late])
        assert window._pending_sources() == ((late,) if cancel else ())
        assert len(notifications) == (0 if cancel else 1)
        if cancel:
            assert window.ui.status_label.text() == "キャンセルしました"
        if not cancel:
            assert window._batch_counts == (2, 0)
    finally:
        release.set()
        if window._thread is not None:
            window._cancel()
            qtbot.waitUntil(lambda: window._thread is None, timeout=5000)


def test_reorder_rejected_after_worker_claim_keeps_display_order(qtbot: QtBot) -> None:
    window = MainWindow()
    qtbot.addWidget(window)
    first, second = Path("first.mp4"), Path("second.mp4")
    window._add_sources((first, second))
    window.ui.file_list.setCurrentRow(1)
    assert window._queue.claim_next() == first
    window._move_selected(-1)
    assert window._sources == [first, second]
    assert "first.mp4" in window.ui.file_list.item(0).text()
    assert window._queue.claim_next() == second


def test_language_change_preserves_running_control_restrictions(qtbot: QtBot) -> None:
    window = MainWindow()
    qtbot.addWidget(window)
    window._add_sources((Path("first.mp4"),))
    window._set_running(True)
    window._cancel_requested = True
    window.ui.lang_en_button.setChecked(True)
    assert not window.ui.start_button.isEnabled()
    assert not window.ui.cancel_button.isEnabled()
    assert not window.ui.output_edit.isEnabled()
    assert not window.ui.model_combo.isEnabled()
    assert not window.ui.delete_model_button.isEnabled()
    window._set_running(False)
    assert window.ui.start_button.isEnabled()
    assert window.ui.output_edit.isEnabled()


def test_queue_refresh_reads_history_once_and_each_source_size_once(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    window = MainWindow()
    qtbot.addWidget(window)
    sources = (tmp_path / "first.mp4", tmp_path / "second.mp4")
    for source in sources:
        source.write_bytes(b"x" * 2000)
    window._add_sources(sources)
    history_reads: list[bool] = []
    size_reads: list[Path] = []
    original_stat = Path.stat

    def history(settings: QSettings) -> tuple[ProcessingMetrics, ...]:
        history_reads.append(True)
        return (ProcessingMetrics("small", 1000, 10.0),)

    def stat(path: Path, **kwargs: Any) -> os.stat_result:
        if path in sources:
            size_reads.append(path)
        return original_stat(path, **kwargs)

    monkeypatch.setattr(main_window, "load_history", history)
    monkeypatch.setattr(Path, "stat", stat)
    window._refresh_queue_display()
    assert history_reads == [True]
    assert size_reads == list(sources)
    assert all(window.ui.file_list.item(i).text().endswith("予測: 20秒") for i in range(2))
    window.ui.model_combo.setCurrentText("tiny")
    assert all(window.ui.file_list.item(i).text().endswith("予測: 履歴なし") for i in range(2))
