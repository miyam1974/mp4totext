from collections.abc import Iterable
from enum import StrEnum
from pathlib import Path


class OutputFormat(StrEnum):
    TXT = "txt"
    JSON = "json"


class OutputExistsError(FileExistsError):
    """Raised when an output exists and overwrite is disabled."""


def output_paths_for(
    source: Path, formats: Iterable[OutputFormat], output_dir: Path | None = None,
) -> tuple[Path, ...]:
    destination = output_dir if output_dir is not None else source.parent
    return tuple(destination / f"{source.stem}.{item.value}" for item in dict.fromkeys(formats))


def output_directory(same_folder: bool, text: str) -> Path | None:
    """An empty custom destination has the same meaning as the source folder."""
    return None if same_folder or not text.strip() else Path(text.strip())


def find_output_collision(
    sources: Iterable[Path], formats: Iterable[OutputFormat], output_dir: Path | None,
) -> Path | None:
    selected = tuple(formats)
    owners: dict[Path, Path] = {}
    for source in sources:
        for path in output_paths_for(source, selected, output_dir):
            key = path.resolve()
            if key in owners and owners[key] != source:
                return path
            owners[key] = source
    return None
