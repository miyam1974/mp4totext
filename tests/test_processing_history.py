from pathlib import Path

import pytest
from PySide6.QtCore import QSettings

from mp4totext.gui.processing_history import (
    ProcessingMetrics,
    append_history,
    estimate_seconds,
    format_duration,
    load_history,
)


def test_estimate_uses_model_specific_median_rate() -> None:
    history = (
        ProcessingMetrics("small", 1000, 10.0),
        ProcessingMetrics("small", 1000, 20.0),
        ProcessingMetrics("tiny", 1000, 1.0),
    )

    assert estimate_seconds("small", 2000, history) == pytest.approx(30.0)
    assert estimate_seconds("medium", 2000, history) is None


def test_history_round_trips_through_settings(tmp_path: Path) -> None:
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    sample = ProcessingMetrics("small", 2048, 12.5)

    append_history(settings, sample)
    settings.sync()

    loaded = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    assert load_history(loaded) == (sample,)


def test_format_duration() -> None:
    assert format_duration(9.6) == "10秒"
    assert format_duration(90) == "1分30秒"
    assert format_duration(3661) == "1時間01分01秒"