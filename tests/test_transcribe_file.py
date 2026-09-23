from pathlib import Path

import pytest

from mp4totext.application import OutputExistsError, OutputFormat, transcribe_file
from mp4totext.domain import ProgressEvent, Segment, Transcript, TranscriptionOptions
from mp4totext.engine import CancellationToken
from mp4totext.engine.protocol import ProgressCallback


class FakeTranscriber:
    def transcribe(
        self,
        source: Path,
        options: TranscriptionOptions,
        progress: ProgressCallback | None = None,
        cancellation: CancellationToken | None = None,
    ) -> Transcript:
        return Transcript("ja", 0.99, 2.0, (Segment(0.0, 2.0, "テストです"),))


def test_transcribe_file_writes_selected_formats(tmp_path: Path) -> None:
    source = tmp_path / "meeting.mp4"
    source.touch()
    events: list[ProgressEvent] = []

    result = transcribe_file(
        source,
        FakeTranscriber(),
        (OutputFormat.TXT, OutputFormat.JSON),
        progress=events.append,
    )

    assert [path.suffix for path in result.output_paths] == [".txt", ".json"]
    assert (tmp_path / "meeting.txt").read_text(encoding="utf-8") == "テストです\n"
    assert events[-1].fraction == 1.0


def test_transcribe_file_does_not_overwrite_by_default(tmp_path: Path) -> None:
    source = tmp_path / "meeting.mp4"
    source.touch()
    (tmp_path / "meeting.txt").write_text("existing", encoding="utf-8")

    with pytest.raises(OutputExistsError):
        transcribe_file(source, FakeTranscriber(), (OutputFormat.TXT,))


def test_transcribe_file_requires_an_output_format(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        transcribe_file(tmp_path / "meeting.mp4", FakeTranscriber(), ())
