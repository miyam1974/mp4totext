from pathlib import Path
from typing import Any

import pytest

from mp4totext.application import OutputFormat, TranscriptionResult
from mp4totext.application.queue import QueueState
from mp4totext.domain import TranscriptionOptions
from mp4totext.engine import TranscriptionCancelled
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

    assert worker.queue.pending() == (sources[2], sources[0])


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

    assert worker.queue.pending() == (added,)
    assert worker.remove_pending(added)
    assert worker.queue.pending() == ()


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


def test_added_files_do_not_inherit_overwrite_permission(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    first, added = tmp_path / "first.mp4", tmp_path / "added.mp4"
    calls: list[tuple[Path, bool]] = []
    monkeypatch.setattr(job_controller, "FasterWhisperTranscriber", object)

    def transcribe(**kwargs: Any) -> TranscriptionResult:
        source = kwargs["source"]
        calls.append((source, kwargs["overwrite"]))
        if source == first:
            worker.add_pending((added,))
        return TranscriptionResult((source.with_suffix(".txt"),), "ja", 1.0)

    monkeypatch.setattr(job_controller, "transcribe_file", transcribe)
    worker = job_controller.TranscriptionWorker(
        (first,), None, (OutputFormat.TXT,), TranscriptionOptions(), True,
    )
    worker.run()
    assert calls == [(first, True), (added, False)]


def test_worker_rejects_collisions_even_when_overwrite_is_allowed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    sources = (tmp_path / "a" / "meeting.mp4", tmp_path / "b" / "meeting.mp4")
    calls: list[Path] = []
    failures: list[Path] = []
    monkeypatch.setattr(job_controller, "FasterWhisperTranscriber", object)

    def transcribe(**kwargs: Any) -> TranscriptionResult:
        calls.append(kwargs["source"])
        return TranscriptionResult((tmp_path / "meeting.txt",), "ja", 1.0)

    monkeypatch.setattr(job_controller, "transcribe_file", transcribe)
    worker = job_controller.TranscriptionWorker(
        sources, tmp_path, (OutputFormat.TXT,), TranscriptionOptions(), True,
    )
    worker.file_failed.connect(lambda source, message: failures.append(source))
    worker.run()
    assert calls == [sources[0]]
    assert failures == [sources[1]]


def test_cancelled_active_file_returns_to_pending(monkeypatch: pytest.MonkeyPatch) -> None:
    source = Path("first.mp4")
    monkeypatch.setattr(job_controller, "FasterWhisperTranscriber", object)

    def cancel(**kwargs: Any) -> TranscriptionResult:
        kwargs["cancellation"].cancel()
        raise TranscriptionCancelled

    monkeypatch.setattr(job_controller, "transcribe_file", cancel)
    worker = job_controller.TranscriptionWorker(
        (source,), None, (OutputFormat.TXT,), TranscriptionOptions(), False,
    )
    worker.run()
    assert worker.queue.pending() == (source,)


def test_file_failure_marks_state_and_continues(monkeypatch: pytest.MonkeyPatch) -> None:
    first, second = Path("first.mp4"), Path("second.mp4")
    monkeypatch.setattr(job_controller, "FasterWhisperTranscriber", object)

    def transcribe(**kwargs: Any) -> TranscriptionResult:
        if kwargs["source"] == first:
            raise OSError("unreadable")
        return TranscriptionResult((second.with_suffix(".txt"),), "ja", 1.0)

    monkeypatch.setattr(job_controller, "transcribe_file", transcribe)
    worker = job_controller.TranscriptionWorker(
        (first, second), None, (OutputFormat.TXT,), TranscriptionOptions(), False,
    )
    worker.run()
    assert [item.state for item in worker.queue.snapshot()] == [
        QueueState.FAILED, QueueState.COMPLETED,
    ]


def test_initialization_failure_reports_error_and_finishes(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail() -> object:
        raise RuntimeError("initialization failed")

    monkeypatch.setattr(job_controller, "FasterWhisperTranscriber", fail)
    worker = job_controller.TranscriptionWorker(
        (Path("first.mp4"),), None, (OutputFormat.TXT,), TranscriptionOptions(), False,
    )
    errors: list[str] = []
    finished: list[bool] = []
    worker.fatal_error.connect(errors.append)
    worker.finished.connect(lambda: finished.append(True))
    worker.run()
    assert len(errors) == 1 and "initialization failed" in errors[0]
    assert finished == [True]
