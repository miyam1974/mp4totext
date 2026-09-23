import os
import tempfile
from pathlib import Path
from typing import Any

import pytest

from mp4totext.output import writer


def test_write_failure_cleans_temporary_and_preserves_existing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = tmp_path / "meeting.txt"
    output.write_text("original", encoding="utf-8")
    create = tempfile.NamedTemporaryFile

    def fail_write(text: str) -> int:
        raise OSError("disk full")

    def failing_file(**kwargs: Any) -> Any:
        stream = create(**kwargs)
        monkeypatch.setattr(stream, "write", fail_write)
        return stream

    monkeypatch.setattr(tempfile, "NamedTemporaryFile", failing_file)
    with pytest.raises(writer.OutputSaveError) as caught:
        writer.write_outputs({output: "new"})
    assert caught.value.committed_paths == ()
    assert output.read_text(encoding="utf-8") == "original"
    assert list(tmp_path.iterdir()) == [output]


def test_replace_failure_reports_partial_save_and_cleans_temporary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    first, second = tmp_path / "meeting.txt", tmp_path / "meeting.json"
    second.write_text("original", encoding="utf-8")
    replace = os.replace

    def fail_second(source: Path, destination: Path) -> None:
        if destination == second:
            raise PermissionError("locked")
        replace(source, destination)

    monkeypatch.setattr(os, "replace", fail_second)
    with pytest.raises(writer.OutputSaveError) as caught:
        writer.write_outputs({first: "new", second: "{}"})
    assert caught.value.committed_paths == (first,)
    assert first.read_text(encoding="utf-8") == "new"
    assert second.read_text(encoding="utf-8") == "original"
    assert set(tmp_path.iterdir()) == {first, second}
