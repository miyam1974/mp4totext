from dataclasses import dataclass
from pathlib import Path

import av


class InvalidMediaError(ValueError):
    """Raised when an input cannot be used for transcription."""


@dataclass(frozen=True, slots=True)
class MediaInfo:
    duration_seconds: float | None
    audio_codec: str | None


def inspect_media(source: Path) -> MediaInfo:
    if not source.is_file():
        raise InvalidMediaError(f"ファイルが見つかりません: {source}")
    if source.suffix.lower() != ".mp4":
        raise InvalidMediaError("MP4ファイルを指定してください")

    try:
        with av.open(str(source)) as container:
            audio_stream = next(iter(container.streams.audio), None)
            if audio_stream is None:
                raise InvalidMediaError("音声トラックが含まれていません")
            duration = float(container.duration / av.time_base) if container.duration else None
            codec = audio_stream.codec_context.name
            return MediaInfo(duration_seconds=duration, audio_codec=codec)
    except InvalidMediaError:
        raise
    except av.FFmpegError as error:
        raise InvalidMediaError("MP4ファイルを読み込めません") from error
