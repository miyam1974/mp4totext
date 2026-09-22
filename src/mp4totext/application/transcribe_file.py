import os
import tempfile
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from mp4totext.domain import ProgressEvent, ProgressStage, TranscriptionOptions
from mp4totext.engine import CancellationToken, Transcriber
from mp4totext.engine.protocol import ProgressCallback
from mp4totext.output import render_json, render_text, summarize


class OutputFormat(StrEnum):
    TXT = "txt"
    JSON = "json"


class OutputExistsError(FileExistsError):
    """Raised when an output exists and overwrite is disabled."""


@dataclass(frozen=True, slots=True)
class TranscriptionResult:
    output_paths: tuple[Path, ...]
    language: str | None
    duration_seconds: float | None


def transcribe_file(
    source: Path,
    transcriber: Transcriber,
    formats: Iterable[OutputFormat],
    options: TranscriptionOptions | None = None,
    output_dir: Path | None = None,
    overwrite: bool = False,
    include_summary: bool = False,
    progress: ProgressCallback | None = None,
    cancellation: CancellationToken | None = None,
) -> TranscriptionResult:
    selected_formats = tuple(dict.fromkeys(formats))
    if not selected_formats:
        raise ValueError("出力形式を1つ以上選択してください")

    destination = output_dir or source.parent
    destination.mkdir(parents=True, exist_ok=True)
    output_paths = tuple(destination / f"{source.stem}.{item.value}" for item in selected_formats)
    existing = next((path for path in output_paths if path.exists()), None)
    if existing is not None and not overwrite:
        raise OutputExistsError(f"出力ファイルが既に存在します: {existing}")

    transcript = transcriber.transcribe(
        source=source,
        options=options or TranscriptionOptions(),
        progress=progress,
        cancellation=cancellation,
    )
    if progress is not None:
        progress(ProgressEvent(ProgressStage.SAVING, None, "結果を保存しています"))

    summary = summarize(transcript.text) if include_summary else None
    renderers = {
        OutputFormat.TXT: lambda item: render_text(item, summary),
        OutputFormat.JSON: lambda item: render_json(item, summary),
    }
    temporary_paths: list[Path] = []
    try:
        for output_format, output_path in zip(selected_formats, output_paths, strict=True):
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                newline="\n",
                prefix=f".{output_path.name}.",
                suffix=".tmp",
                dir=destination,
                delete=False,
            ) as temporary:
                temporary.write(renderers[output_format](transcript))
                temporary_paths.append(Path(temporary.name))
        for temporary_path, output_path in zip(temporary_paths, output_paths, strict=True):
            os.replace(temporary_path, output_path)
    finally:
        for temporary_path in temporary_paths:
            temporary_path.unlink(missing_ok=True)

    if progress is not None:
        progress(ProgressEvent(ProgressStage.COMPLETED, 1.0, "完了しました"))
    return TranscriptionResult(output_paths, transcript.language, transcript.duration_seconds)
