from pathlib import Path

from mp4totext.application import OutputFormat
from mp4totext.application.output_plan import (
    find_output_collision,
    output_directory,
    output_paths_for,
)


def test_empty_destination_and_format_deduplication(tmp_path: Path) -> None:
    source = tmp_path / "meeting.mp4"
    destination = output_directory(False, "  ")
    assert destination is None
    assert output_paths_for(source, (OutputFormat.TXT, OutputFormat.TXT), destination) == (
        source.with_suffix(".txt"),
    )
    assert output_directory(False, f"  {tmp_path}  ") == tmp_path


def test_same_names_collide_only_with_shared_destination(tmp_path: Path) -> None:
    sources = (tmp_path / "a" / "meeting.mp4", tmp_path / "b" / "meeting.mp4")
    formats = (OutputFormat.TXT,)
    assert find_output_collision(sources, formats, None) is None
    assert find_output_collision(sources, formats, tmp_path) == tmp_path / "meeting.txt"
