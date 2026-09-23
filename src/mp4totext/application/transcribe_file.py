from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from mp4totext.application.output_plan import OutputExistsError, OutputFormat, output_paths_for
from mp4totext.domain import ProgressEvent, ProgressStage, TranscriptionOptions
from mp4totext.engine import CancellationToken, Transcriber
from mp4totext.engine.protocol import ProgressCallback
from mp4totext.output import render_json, render_text
from mp4totext.output.writer import write_outputs


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
    progress: ProgressCallback | None = None,
    cancellation: CancellationToken | None = None,
) -> TranscriptionResult:
    selected_formats = tuple(dict.fromkeys(formats))
    if not selected_formats:
        raise ValueError("出力形式を1つ以上選択してください")

    output_paths = output_paths_for(source, selected_formats, output_dir)
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

    renderers = {
        OutputFormat.TXT: render_text,
        OutputFormat.JSON: render_json,
    }
    write_outputs({
        path: renderers[output_format](transcript)
        for output_format, path in zip(selected_formats, output_paths, strict=True)
    })

    if progress is not None:
        progress(ProgressEvent(ProgressStage.COMPLETED, 1.0, "完了しました"))
    return TranscriptionResult(output_paths, transcript.language, transcript.duration_seconds)
