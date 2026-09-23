import os
import tempfile
from collections.abc import Mapping
from pathlib import Path


class OutputSaveError(OSError):
    """A failed save, including any output files already committed."""

    def __init__(self, committed_paths: tuple[Path, ...]) -> None:
        self.committed_paths = committed_paths
        super().__init__(
            "Could not save all outputs. Already saved: "
            + (", ".join(map(str, committed_paths)) or "none")
        )


def write_outputs(documents: Mapping[Path, str]) -> None:
    """Stage all content before replacing outputs; report partial commits explicitly."""
    temporary_paths: list[Path] = []
    committed: list[Path] = []
    try:
        for output_path, text in documents.items():
            output_path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", newline="\n",
                prefix=f".{output_path.name}.", suffix=".tmp",
                dir=output_path.parent, delete=False,
            ) as temporary:
                temporary_paths.append(Path(temporary.name))
                temporary.write(text)
        for temporary_path, output_path in zip(temporary_paths, documents, strict=True):
            os.replace(temporary_path, output_path)
            committed.append(output_path)
    except OSError as error:
        raise OutputSaveError(tuple(committed)) from error
    finally:
        for temporary_path in temporary_paths:
            temporary_path.unlink(missing_ok=True)
