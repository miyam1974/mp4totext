from pathlib import Path
from typing import Annotated

import typer

from mp4totext.application import OutputExistsError, OutputFormat, transcribe_file
from mp4totext.domain import ProgressEvent, TranscriptionOptions
from mp4totext.engine import TranscriptionCancelled
from mp4totext.engine.faster_whisper import FasterWhisperTranscriber
from mp4totext.media import InvalidMediaError

app = typer.Typer(
    name="mp4totext",
    help="MP4ファイルを端末内で文字起こしします。",
    no_args_is_help=True,
)


@app.command()
def transcribe(
    source: Annotated[
        Path,
        typer.Argument(help="文字起こしするMP4ファイル", exists=True, dir_okay=False),
    ],
    output_format: Annotated[
        list[OutputFormat] | None,
        typer.Option("--format", "-f", help="出力形式。複数回指定できます。"),
    ] = None,
    output_dir: Annotated[
        Path | None,
        typer.Option("--output-dir", "-o", help="出力先フォルダー"),
    ] = None,
    model: Annotated[
        str,
        typer.Option(help="Whisperモデル名 (tiny/base/small/medium)"),
    ] = "small",
    language: Annotated[
        str | None,
        typer.Option(help="言語コード。省略時は自動判定します。"),
    ] = None,
    overwrite: Annotated[
        bool,
        typer.Option("--overwrite", help="既存の出力ファイルを上書きします。"),
    ] = False,
) -> None:
    """MP4からTXTまたはJSONを生成します。"""
    formats = output_format or [OutputFormat.TXT]
    try:
        result = transcribe_file(
            source=source,
            transcriber=FasterWhisperTranscriber(),
            formats=formats,
            options=TranscriptionOptions(model_name=model, language=language),
            output_dir=output_dir,
            overwrite=overwrite,
            progress=_show_progress,
        )
    except (InvalidMediaError, OutputExistsError, ValueError) as error:
        typer.secho(f"エラー: {error}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2) from error
    except TranscriptionCancelled as error:
        typer.secho("文字起こしをキャンセルしました。", fg=typer.colors.YELLOW, err=True)
        raise typer.Exit(code=130) from error
    except (OSError, RuntimeError) as error:
        typer.secho(f"文字起こしに失敗しました: {error}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from error

    typer.secho("生成ファイル:", fg=typer.colors.GREEN)
    for path in result.output_paths:
        typer.echo(f"  {path}")


def _show_progress(event: ProgressEvent) -> None:
    if event.fraction is None:
        typer.echo(event.message)
    else:
        typer.echo(f"{event.message}: {event.fraction:.0%}")


if __name__ == "__main__":
    app()