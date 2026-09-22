from pathlib import Path
from types import SimpleNamespace

import pytest

from mp4totext.engine import model_cache


def test_inspect_model_cache_reports_download_and_size(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    cache_dir = tmp_path / "models"
    cache_dir.mkdir()
    repo = SimpleNamespace(
        repo_id="Systran/faster-whisper-small",
        revisions={object()},
        size_on_disk=486_212_372,
    )
    monkeypatch.setattr(model_cache, "model_cache_dir", lambda: cache_dir)
    monkeypatch.setattr(
        model_cache,
        "scan_cache_dir",
        lambda path: SimpleNamespace(repos=(repo,)),
    )

    status = model_cache.inspect_model_cache("small")

    assert status.downloaded
    assert model_cache.format_size(status.size_bytes) == "463.7 MiB"


def test_delete_app_cache_keeps_parent_and_siblings(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    app_root = tmp_path / "mp4totext"
    cache_dir = app_root / "Cache"
    cache_dir.mkdir(parents=True)
    (cache_dir / "model.bin").write_bytes(b"model")
    sibling = app_root / "keep.txt"
    sibling.write_text("keep", encoding="utf-8")
    monkeypatch.setattr(model_cache, "app_cache_dir", lambda: cache_dir)

    model_cache.delete_app_cache()

    assert not cache_dir.exists()
    assert sibling.exists()


def test_delete_app_cache_rejects_unexpected_path(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(model_cache, "app_cache_dir", lambda: tmp_path)

    with pytest.raises(RuntimeError):
        model_cache.delete_app_cache()


def test_delete_model_cache_removes_residual_repo_and_lock(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    cache_dir = tmp_path / "models"
    repo_path = cache_dir / "models--Systran--faster-whisper-small"
    lock_dir = cache_dir / ".locks" / repo_path.name
    repo_path.mkdir(parents=True)
    lock_dir.mkdir(parents=True)
    revision = SimpleNamespace(commit_hash="abc123")
    repo = SimpleNamespace(
        repo_id="Systran/faster-whisper-small",
        repo_path=repo_path,
        revisions=(revision,),
    )
    strategy = SimpleNamespace(expected_freed_size=123, execute=lambda: None)
    cache = SimpleNamespace(
        repos=(repo,),
        delete_revisions=lambda *revisions: strategy,
    )
    monkeypatch.setattr(model_cache, "model_cache_dir", lambda: cache_dir)
    monkeypatch.setattr(model_cache, "scan_cache_dir", lambda path: cache)
    monkeypatch.setattr(model_cache, "close_session", lambda: None)

    freed = model_cache.delete_model_cache("small")

    assert freed == 123
    assert not repo_path.exists()
    assert not lock_dir.exists()