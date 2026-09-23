import time
import traceback
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QObject, Signal, Slot

from mp4totext.application import OutputFormat, transcribe_file
from mp4totext.application.output_plan import OutputExistsError, output_paths_for
from mp4totext.application.queue import QueueState, TranscriptionQueue
from mp4totext.domain import ProgressEvent, TranscriptionOptions
from mp4totext.domain.processing_history import ProcessingMetrics
from mp4totext.engine import CancellationToken, TranscriptionCancelled
from mp4totext.engine.faster_whisper import FasterWhisperTranscriber


class TranscriptionWorker(QObject):
    progress = Signal(object)
    file_started = Signal(object, int, int, int)
    file_completed = Signal(object, object, object)
    file_failed = Signal(object, str)
    batch_completed = Signal(int, int)
    cancelled = Signal()
    fatal_error = Signal(str)
    finished = Signal()

    def __init__(
        self,
        sources: tuple[Path, ...],
        output_dir: Path | None,
        formats: tuple[OutputFormat, ...],
        options: TranscriptionOptions,
        overwrite: bool,
        clock: Callable[[], float] = time.monotonic,
        queue: TranscriptionQueue | None = None,
    ) -> None:
        super().__init__()
        self.queue = queue if queue is not None else TranscriptionQueue(sources)
        self._output_dir = output_dir
        self._formats = formats
        self._options = options
        self._overwrite_sources = frozenset(sources) if overwrite else frozenset()
        self._clock = clock
        self._cancellation = CancellationToken()

    @Slot()
    def run(self) -> None:
        completed = 0
        failed = 0
        started = 0
        output_owners: dict[Path, Path] = {}
        source: Path | None = None
        try:
            transcriber = FasterWhisperTranscriber()
            while True:
                self._cancellation.raise_if_cancelled()
                source = self.queue.claim_next()
                if source is None:
                    break
                started += 1
                try:
                    file_size = source.stat().st_size if source.is_file() else 0
                    started_at = self._clock()
                    self.file_started.emit(
                        source, started, started + len(self.queue.pending()), file_size,
                    )
                    for path in output_paths_for(source, self._formats, self._output_dir):
                        key = path.resolve()
                        if key in output_owners and output_owners[key] != source:
                            raise OutputExistsError(
                                f"Output path is shared by multiple videos: {path}"
                            )
                        output_owners[key] = source
                    result = transcribe_file(
                        source=source,
                        transcriber=transcriber,
                        formats=self._formats,
                        options=self._options,
                        output_dir=self._output_dir,
                        overwrite=source in self._overwrite_sources,
                        progress=self._emit_progress,
                        cancellation=self._cancellation,
                    )
                except TranscriptionCancelled:
                    raise
                except Exception:
                    failed += 1
                    self.queue.set_state(source, QueueState.FAILED)
                    self.file_failed.emit(source, traceback.format_exc())
                    continue
                completed += 1
                self.queue.set_state(source, QueueState.COMPLETED)
                metrics = ProcessingMetrics(
                    model_name=self._options.model_name,
                    file_size_bytes=file_size,
                    elapsed_seconds=max(self._clock() - started_at, 0.0),
                )
                self.file_completed.emit(source, result, metrics)
            self.batch_completed.emit(completed, failed)
        except TranscriptionCancelled:
            if source is not None:
                # Only an interrupted active file returns to pending.
                for item in self.queue.snapshot():
                    if item.source == source and item.state is QueueState.ACTIVE:
                        self.queue.set_state(source, QueueState.PENDING)
            self.cancelled.emit()
        except Exception:
            self.fatal_error.emit(traceback.format_exc())
        finally:
            self.finished.emit()

    def cancel(self) -> None:
        self._cancellation.cancel()

    def remove_pending(self, source: Path) -> bool:
        return self.queue.remove(source, pending_only=True)

    def add_pending(self, sources: tuple[Path, ...]) -> None:
        self.queue.add(sources)

    def reorder_pending(self, sources: tuple[Path, ...]) -> bool:
        return self.queue.reorder_pending(sources)

    def _emit_progress(self, event: ProgressEvent) -> None:
        self.progress.emit(event)
