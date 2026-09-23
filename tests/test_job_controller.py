from pathlib import Path
from typing import Any, cast

import pytest

from mp4totext.application import OutputFormat, TranscriptionResult
from mp4totext.domain import TranscriptionOptions
from mp4totext.gui import job_controller
from mp4totext.gui.processing_history import ProcessingMetrics


def test_worker_processes_files_in_order_with_one_transcriber(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sources = (Path("first.mp4"), Path("second.mp4"))
    calls: list[tuple[Path, object]] = []
    transcriber = object()

    monkeypatch.setattr(job_controller, "FasterWhisperTranscriber", lambda: transcriber)

    def fake_transcribe_file(**kwargs: Any) -> TranscriptionResult:
        calls.append((kwargs["source"], kwargs["transcriber"]))
        return TranscriptionResult((kwargs["source"].with_suffix(".txt"),), "ja", 1.0)

    monkeypatch.setattr(job_controller, "transcribe_file", fake_transcribe_file)
    worker = job_controller.TranscriptionWorker(
        sources,
        None,
        (OutputFormat.TXT,),
        TranscriptionOptions(),
        False,
    )
    started: list[Path] = []
    worker.file_started.connect(lambda source, index, total: started.append(source))

    worker.run()

    assert started == list(sources)
    assert calls == [(sources[0], transcriber), (sources[1], transcriber)]


def test_worker_can_remove_and_reorder_pending_files() -> None:
    sources = (Path("first.mp4"), Path("second.mp4"), Path("third.mp4"))
    worker = job_controller.TranscriptionWorker(
        sources,
        None,
        (OutputFormat.TXT,),
        TranscriptionOptions(),
        False,
    )

    assert worker.remove_pending(sources[1])
    worker.reorder_pending((sources[2], sources[0]))

    assert cast(Any, worker)._pending == [sources[2], sources[0]]


def test_worker_can_add_and_then_remove_a_pending_file() -> None:
    worker = job_controller.TranscriptionWorker(
        (),
        None,
        (OutputFormat.TXT,),
        TranscriptionOptions(),
        False,
    )
    added = Path("added.mp4")

    worker.add_pending((added,))

    assert cast(Any, worker)._pending == [added]
    assert worker.remove_pending(added)
    assert cast(Any, worker)._pending == []


def test_worker_reports_file_size_model_and_elapsed_time(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "meeting.mp4"
    source.write_bytes(b"x" * 4096)
    times = iter((100.0, 112.5))
    monkeypatch.setattr(job_controller, "FasterWhisperTranscriber", object)
    monkeypatch.setattr(
        job_controller,
        "transcribe_file",
        lambda **kwargs: TranscriptionResult((source.with_suffix(".txt"),), "ja", 60.0),
    )
    worker = job_controller.TranscriptionWorker(
        (source,),
        None,
        (OutputFormat.TXT,),
        TranscriptionOptions(model_name="small"),
        False,
        clock=lambda: next(times),
    )
    started: list[tuple[Path, int]] = []
    completed: list[ProcessingMetrics] = []
    worker.file_started.connect(
        lambda path, index, total, size: started.append((path, size))
    )
    worker.file_completed.connect(
        lambda path, result, metrics: completed.append(metrics)
    )

    worker.run()

    assert started == [(source, 4096)]
    assert completed == [ProcessingMetrics("small", 4096, 12.5)]