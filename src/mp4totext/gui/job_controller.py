import time
import traceback
from collections.abc import Callable
from pathlib import Path
from threading import Lock

from PySide6.QtCore import QObject, Signal, Slot

from mp4totext.application import OutputFormat, transcribe_file
from mp4totext.domain import ProgressEvent, TranscriptionOptions
from mp4totext.engine import CancellationToken, TranscriptionCancelled
from mp4totext.engine.faster_whisper import FasterWhisperTranscriber
from mp4totext.gui.processing_history import ProcessingMetrics


class TranscriptionWorker(QObject):
    progress = Signal(object)
    file_started = Signal(object, int, int, int)
    file_completed = Signal(object, object, object)
    file_failed = Signal(object, str)
    batch_completed = Signal(int, int)
    cancelled = Signal()
    finished = Signal()

    def __init__(
        self,
        sources: tuple[Path, ...],
        output_dir: Path | None,
        formats: tuple[OutputFormat, ...],
        options: TranscriptionOptions,
        overwrite: bool,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        super().__init__()
        self._pending = list(sources)
        self._pending_lock = Lock()
        self._output_dir = output_dir
        self._formats = formats
        self._options = options
        self._overwrite = overwrite
        self._clock = clock
        self._cancellation = CancellationToken()

    @Slot()
    def run(self) -> None:
        completed = 0
        failed = 0
        started = 0
        transcriber = FasterWhisperTranscriber()
        try:
            while True:
                with self._pending_lock:
                    if not self._pending:
                        break
                    source = self._pending.pop(0)
                    total = started + 1 + len(self._pending)
                started += 1
                self._cancellation.raise_if_cancelled()
                file_size = source.stat().st_size if source.is_file() else 0
                started_at = self._clock()
                self.file_started.emit(source, started, total, file_size)
                try:
                    result = transcribe_file(
                        source=source,
                        transcriber=transcriber,
                        formats=self._formats,
                        options=self._options,
                        output_dir=self._output_dir,
                        overwrite=self._overwrite,
                        progress=self._emit_progress,
                        cancellation=self._cancellation,
                    )
                except TranscriptionCancelled:
                    raise
                except Exception:
                    failed += 1
                    self.file_failed.emit(source, traceback.format_exc())
                    continue
                completed += 1
                metrics = ProcessingMetrics(
                    model_name=self._options.model_name,
                    file_size_bytes=file_size,
                    elapsed_seconds=max(self._clock() - started_at, 0.0),
                )
                self.file_completed.emit(source, result, metrics)
            self.batch_completed.emit(completed, failed)
        except TranscriptionCancelled:
            self.cancelled.emit()
        finally:
            self.finished.emit()

    def cancel(self) -> None:
        self._cancellation.cancel()

    def remove_pending(self, source: Path) -> bool:
        with self._pending_lock:
            if source not in self._pending:
                return False
            self._pending.remove(source)
            return True

    def reorder_pending(self, sources: tuple[Path, ...]) -> None:
        with self._pending_lock:
            if set(sources) == set(self._pending):
                self._pending[:] = sources

    def _emit_progress(self, event: ProgressEvent) -> None:
        self.progress.emit(event)
