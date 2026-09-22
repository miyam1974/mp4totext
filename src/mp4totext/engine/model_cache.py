import shutil
from dataclasses import dataclass
from pathlib import Path

from huggingface_hub import close_session, scan_cache_dir
from huggingface_hub.errors import CacheNotFound
from platformdirs import user_cache_path

MODEL_REPOSITORIES = {
    "tiny": "Systran/faster-whisper-tiny",
    "base": "Systran/faster-whisper-base",
    "small": "Systran/faster-whisper-small",
    "medium": "Systran/faster-whisper-medium",
}


@dataclass(frozen=True, slots=True)
class ModelCacheStatus:
    model_name: str
    downloaded: bool
    size_bytes: int = 0


def model_cache_dir() -> Path:
    return user_cache_path("mp4totext", appauthor=False) / "models"


def app_cache_dir() -> Path:
    return user_cache_path("mp4totext", appauthor=False)


def inspect_model_cache(model_name: str) -> ModelCacheStatus:
    repository = _repository_for(model_name)
    cache_dir = model_cache_dir()
    if not cache_dir.is_dir():
        return ModelCacheStatus(model_name, False)
    try:
        cache = scan_cache_dir(cache_dir)
    except CacheNotFound:
        return ModelCacheStatus(model_name, False)
    repo = next((item for item in cache.repos if item.repo_id == repository), None)
    if repo is None or not repo.revisions:
        return ModelCacheStatus(model_name, False)
    return ModelCacheStatus(model_name, True, repo.size_on_disk)


def delete_model_cache(model_name: str) -> int:
    repository = _repository_for(model_name)
    cache_dir = model_cache_dir()
    if not cache_dir.is_dir():
        return 0
    try:
        cache = scan_cache_dir(cache_dir)
    except CacheNotFound:
        return 0
    repo = next((item for item in cache.repos if item.repo_id == repository), None)
    if repo is None:
        return 0
    revisions = tuple(revision.commit_hash for revision in repo.revisions)
    strategy = cache.delete_revisions(*revisions)
    close_session()
    strategy.execute()
    if repo.repo_path.exists():
        shutil.rmtree(repo.repo_path)
    lock_dir = cache_dir / ".locks" / repo.repo_path.name
    if lock_dir.exists():
        shutil.rmtree(lock_dir)
    if repo.repo_path.exists():
        raise OSError(f"モデルキャッシュを削除できません: {repo.repo_path}")
    return strategy.expected_freed_size


def delete_app_cache() -> None:
    cache_dir = app_cache_dir().resolve()
    if cache_dir.name != "Cache" or cache_dir.parent.name.lower() != "mp4totext":
        raise RuntimeError("アプリデータの保存先を安全に確認できません")
    if cache_dir.is_dir():
        close_session()
        shutil.rmtree(cache_dir)


def format_size(size_bytes: int) -> str:
    size = float(size_bytes)
    for unit in ("B", "KiB", "MiB", "GiB"):
        if size < 1024 or unit == "GiB":
            return f"{size:.1f} {unit}"
        size /= 1024
    raise AssertionError("unreachable")


def _repository_for(model_name: str) -> str:
    try:
        return MODEL_REPOSITORIES[model_name]
    except KeyError as error:
        raise ValueError(f"未対応のモデルです: {model_name}") from error