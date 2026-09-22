from collections.abc import Callable
from pathlib import Path
from threading import Event
from typing import Protocol

from mp4totext.domain import ProgressEvent, Transcript, TranscriptionOptions

ProgressCallback = Callable[[ProgressEvent], None]


class TranscriptionCancelled(Exception):
    """Raised when the user cancels an active transcription."""


class CancellationToken:
    def __init__(self) -> None:
        self._cancelled = Event()

    @property
    def is_cancelled(self) -> bool:
        return self._cancelled.is_set()

    def cancel(self) -> None:
        self._cancelled.set()

    def raise_if_cancelled(self) -> None:
        if self.is_cancelled:
            raise TranscriptionCancelled


class Transcriber(Protocol):
    def transcribe(
        self,
        source: Path,
        options: TranscriptionOptions,
        progress: ProgressCallback | None = None,
        cancellation: CancellationToken | None = None,
    ) -> Transcript: ...
