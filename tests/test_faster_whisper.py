import sys
from pathlib import Path
from typing import Any

import pytest

from mp4totext.domain import ProgressEvent
from mp4totext.engine import CancellationToken, TranscriptionCancelled
from mp4totext.engine import faster_whisper as backend
from mp4totext.engine.faster_whisper import _contains_certificate_error


def test_detects_nested_certificate_verification_error() -> None:
    certificate_error = RuntimeError(
        "[SSL: CERTIFICATE_VERIFY_FAILED] self-signed certificate in certificate chain"
    )
    outer_error = RuntimeError("model download failed")
    outer_error.__cause__ = certificate_error

    assert _contains_certificate_error(outer_error)


def test_does_not_treat_other_download_errors_as_certificate_errors() -> None:
    assert not _contains_certificate_error(RuntimeError("connection timed out"))


def test_resolve_model_reuses_local_cache_without_online_request(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    calls: list[bool] = []

    def fake_snapshot_download(repository: str, **kwargs: Any) -> str:
        calls.append(bool(kwargs.get("local_files_only")))
        return str(tmp_path / repository.replace("/", "--"))

    monkeypatch.setattr(backend, "snapshot_download", fake_snapshot_download)

    result = backend._resolve_model("small", None, CancellationToken())

    assert result.endswith("Systran--faster-whisper-small")
    assert calls == [True]


def test_download_progress_reports_fraction() -> None:
    events: list[ProgressEvent] = []
    progress_type = backend._progress_tqdm(events.append, CancellationToken())

    progress = progress_type(total=10, desc="モデル取得中")
    progress.update(4)
    progress.close()

    assert events[-1].fraction == pytest.approx(0.4)


def test_download_progress_works_without_stderr(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "stderr", None)
    progress_type = backend._progress_tqdm(None, CancellationToken())

    progress = progress_type(total=10, desc="モデル取得中")
    progress.update(4)
    progress.close()


def test_download_progress_observes_cancellation() -> None:
    cancellation = CancellationToken()
    progress_type = backend._progress_tqdm(None, cancellation)
    progress = progress_type(total=10)
    cancellation.cancel()

    with pytest.raises(TranscriptionCancelled):
        progress.update(1)

    progress.close()