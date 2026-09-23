import json
from pathlib import Path

import pytest
from PySide6.QtCore import QSettings

from mp4totext.domain.processing_history import ProcessingMetrics
from mp4totext.gui.history_store import append_history, load_history


def test_existing_history_format_and_round_trip(tmp_path: Path) -> None:
    path = str(tmp_path / "settings.ini")
    settings = QSettings(path, QSettings.Format.IniFormat)
    settings.setValue("processing/history/v1", json.dumps([
        {"model_name": "small", "file_size_bytes": 2048, "elapsed_seconds": 12.5},
    ]))
    sample = ProcessingMetrics("small", 2048, 12.5)
    assert load_history(settings) == (sample,)
    next_sample = ProcessingMetrics("tiny", 1024, 2.0)
    append_history(settings, next_sample)
    settings.sync()
    assert load_history(QSettings(path, QSettings.Format.IniFormat)) == (sample, next_sample)


@pytest.mark.parametrize("raw", ["", "broken", "null", "{}", '[null, {}, "bad"]'])
def test_invalid_history_is_ignored(tmp_path: Path, raw: str) -> None:
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    settings.setValue("processing/history/v1", raw)
    assert load_history(settings) == ()


def test_invalid_records_do_not_discard_valid_samples(tmp_path: Path) -> None:
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    valid = {"model_name": "small", "file_size_bytes": 1000, "elapsed_seconds": 10.0}
    settings.setValue("processing/history/v1", json.dumps([
        {**valid, "file_size_bytes": float("inf")},
        {**valid, "elapsed_seconds": float("nan")},
        {**valid, "model_name": None},
        valid,
    ]))
    assert load_history(settings) == (ProcessingMetrics("small", 1000, 10.0),)
    append_history(settings, ProcessingMetrics("small", 1000, float("nan")))
    assert "NaN" not in str(settings.value("processing/history/v1"))
    assert load_history(settings) == (ProcessingMetrics("small", 1000, 10.0),)


def test_store_retains_only_latest_twenty_samples(tmp_path: Path) -> None:
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    for index in range(25):
        append_history(settings, ProcessingMetrics("small", 1000, index + 1.0))
    assert [sample.elapsed_seconds for sample in load_history(settings)] == list(range(6, 26))
