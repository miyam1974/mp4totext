from pathlib import Path

import pytest
from PySide6.QtCore import QSettings

from mp4totext.gui import main_window


@pytest.fixture(autouse=True)
def isolate_qsettings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Redirect MainWindow's default QSettings("mp4totext", "mp4totext") to a
    temp .ini file so tests never overwrite the shipped app's real settings.

    QSettings(organization, application) hardcodes the native format (Windows
    registry), so QSettings.setDefaultFormat()/setPath() cannot redirect it.
    """
    settings_path = str(tmp_path / "settings.ini")
    monkeypatch.setattr(
        main_window,
        "QSettings",
        lambda *args, **kwargs: QSettings(settings_path, QSettings.Format.IniFormat),
    )

