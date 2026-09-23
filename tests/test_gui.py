import os
from pathlib import Path
from typing import Any, cast

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication
from pytestqt.qtbot import QtBot

from mp4totext.application import OutputFormat, TranscriptionResult
from mp4totext.domain import ProgressEvent, ProgressStage
from mp4totext.engine.model_cache import ModelCacheStatus
from mp4totext.gui import main_window
from mp4totext.gui.main_window import MainWindow, QueueState
from mp4totext.gui.processing_history import ProcessingMetrics, append_history, load_history


def test_window_accepts_a_selected_mp4(qtbot: QtBot) -> None:
    window = MainWindow()
    qtbot.addWidget(window)

    window._add_sources((Path("meeting.mp4"), Path("review.mp4")))

    assert window.start_button.isEnabled()
    assert window.drop_area.label.text() == "2 ファイルを選択中"
    assert window.file_list.count() == 2
    assert window._selected_formats() == (OutputFormat.TXT,)
    assert window.file_list.item(0).text().endswith("/ 予測: 算出不可")


def test_sources_can_be_added_while_transcription_is_running(qtbot: QtBot) -> None:
    window = MainWindow()
    qtbot.addWidget(window)
    window._add_sources((Path("meeting.mp4"),))
    window._set_running(True)
    cast(Any, window)._thread = object()

    assert window.drop_area.isEnabled()

    window._add_sources((Path("review.mp4"),))

    assert window.file_list.count() == 2
    assert not window.start_button.isEnabled()

    cast(Any, window)._thread = None


def test_window_requires_at_least_one_output_format(qtbot: QtBot) -> None:
    window = MainWindow()
    qtbot.addWidget(window)

    window.txt_check.setChecked(False)

    assert window._selected_formats() == ()


def test_window_shows_active_file(qtbot: QtBot) -> None:
    window = MainWindow()
    qtbot.addWidget(window)
    source = Path("review.mp4")
    window._add_sources((Path("meeting.mp4"), source))

    window._on_file_started(source, 2, 2, 2048)

    assert window.file_list.currentRow() == 1
    assert window.file_list.item(1).text() == "[処理中] review.mp4 / 予測: 算出不可"
    assert window.active_file_label.text() == "処理中: review.mp4 (2/2)"
    assert window.timing_label.text().startswith("サイズ: 2.0 KiB / 予測: ")
    assert window.timing_label.text().endswith("/ 経過: 0秒")


def test_pending_files_can_be_reordered_and_removed(qtbot: QtBot) -> None:
    window = MainWindow()
    qtbot.addWidget(window)
    window._add_sources((Path("first.mp4"), Path("second.mp4")))

    window.file_list.setCurrentRow(1)
    window._move_selected(-1)
    window._remove_selected()

    assert window._sources == [Path("first.mp4")]


def test_processed_file_cannot_be_removed(qtbot: QtBot) -> None:
    window = MainWindow()
    qtbot.addWidget(window)
    window._add_sources((Path("done.mp4"),))
    window._states[0] = QueueState.COMPLETED
    window.file_list.setCurrentRow(0)

    window._remove_selected()

    assert window._sources == [Path("done.mp4")]


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

    assert window.model_status_label.text() == "モデル: small / ダウンロード済み (463.7 MiB)"
    window.model_combo.setCurrentText("tiny")
    assert window.model_status_label.text() == "モデル: tiny / 未ダウンロード"


def test_debug_output_is_scrollable_and_copyable(qtbot: QtBot) -> None:
    window = MainWindow()
    qtbot.addWidget(window)
    source = Path("failed.mp4")
    window._add_sources((source,))
    details = "Traceback\n" + "\n".join(f"line {index}" for index in range(50))

    window._on_file_failed(source, details)
    window._copy_debug_info()

    assert "Traceback" in window.debug_output.toPlainText()
    assert window.debug_output.verticalScrollBar().maximum() > 0
    assert QApplication.clipboard().text() == window.debug_output.toPlainText()


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

    assert window.model_status_label.text() == "モデル: small / ダウンロード中 (40%)"
    assert window.cancel_button.isEnabled()
    assert window.cancel_button.text() == "モデル取得をキャンセル"

    downloaded = True
    window._on_progress(ProgressEvent(ProgressStage.TRANSCRIBING, 0.0, "文字起こし中"))

    assert window.model_status_label.text() == "モデル: small / ダウンロード済み (1.0 KiB)"
    assert window.cancel_button.text() == "キャンセル"


def test_cancelling_active_file_allows_restarting_the_queue(qtbot: QtBot) -> None:
    window = MainWindow()
    qtbot.addWidget(window)
    source = Path("meeting.mp4")
    window._add_sources((source,))
    window._on_file_started(source, 1, 1, 0)

    window._on_cancelled()
    window._job_finished()

    assert window._states == [QueueState.PENDING]
    assert window.file_list.item(0).text().startswith("[待機]")
    assert window.start_button.isEnabled()


def test_window_uses_requested_initial_height(qtbot: QtBot) -> None:
    window = MainWindow()
    qtbot.addWidget(window)

    assert window.height() == 604


def test_open_output_directory_uses_selected_destination(
    qtbot: QtBot,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    opened: list[Path] = []
    monkeypatch.setattr(os, "startfile", lambda path: opened.append(Path(path)))
    window = MainWindow()
    qtbot.addWidget(window)
    window.output_edit.setText(str(tmp_path))

    window._open_output_dir()

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
    first_window.output_edit.setText(str(output_dir))
    first_window._save_output_dir()
    first_settings.sync()

    second_settings = QSettings(str(settings_path), QSettings.Format.IniFormat)
    second_window = MainWindow(second_settings)
    qtbot.addWidget(second_window)

    assert second_window.output_edit.text() == str(output_dir)


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
    window.output_edit.setText(str(tmp_path))

    window._add_sources((source,))

    assert window.file_list.item(0).text() == (
        "[待機 / 文字起こし済み] meeting.mp4 / 予測: 履歴なし"
    )

    window.json_check.setChecked(True)
    assert window.file_list.item(0).text() == "[待機] meeting.mp4 / 予測: 履歴なし"

    (tmp_path / "meeting.json").write_text("{}", encoding="utf-8")
    window._refresh_queue_display()
    assert window.file_list.item(0).text() == (
        "[待機 / 文字起こし済み] meeting.mp4 / 予測: 履歴なし"
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

    assert window.file_list.item(0).text().endswith("/ 予測: 20秒")

    window._on_file_started(source, 1, 1, 2000)

    assert window.timing_label.text() == "サイズ: 2.0 KiB / 予測: 20秒 / 経過: 0秒"

    result = TranscriptionResult((tmp_path / "meeting.txt",), "ja", 60.0)
    metrics = ProcessingMetrics("small", 2000, 25.0)
    window._on_file_completed(source, result, metrics)

    assert window.timing_label.text() == "サイズ: 2.0 KiB / 予測: 20秒 / 経過: 25秒"
    assert load_history(settings)[-1] == metrics
