from pathlib import Path
from typing import Any, cast

import truststore
from faster_whisper import WhisperModel
from huggingface_hub import snapshot_download
from huggingface_hub.errors import LocalEntryNotFoundError
from tqdm import tqdm

from mp4totext.domain import (
    ProgressEvent,
    ProgressStage,
    Segment,
    Transcript,
    TranscriptionOptions,
)
from mp4totext.engine.model_cache import MODEL_REPOSITORIES, model_cache_dir
from mp4totext.engine.protocol import CancellationToken, ProgressCallback
from mp4totext.media import inspect_media

_MODEL_FILES = [
    "config.json",
    "preprocessor_config.json",
    "model.bin",
    "tokenizer.json",
    "vocabulary.*",
]


class _NullProgressStream:
    def write(self, text: str) -> int:
        return len(text)

    def flush(self) -> None:
        pass


_NULL_PROGRESS_STREAM = _NullProgressStream()


class FasterWhisperTranscriber:
    def __init__(self) -> None:
        self._models: dict[tuple[str, str], WhisperModel] = {}

    def transcribe(
        self,
        source: Path,
        options: TranscriptionOptions,
        progress: ProgressCallback | None = None,
        cancellation: CancellationToken | None = None,
    ) -> Transcript:
        token = cancellation or CancellationToken()
        self._report(progress, ProgressStage.PREPARING, 0.0, "MP4を確認しています")
        media = inspect_media(source)
        token.raise_if_cancelled()

        model_key = (options.model_name, options.compute_type)
        if model_key not in self._models:
            self._report(
                progress,
                ProgressStage.DOWNLOADING_MODEL,
                None,
                "文字起こしモデルを準備しています",
            )
            try:
                model_path = _resolve_model(
                    options.model_name,
                    progress,
                    token,
                )
                self._models[model_key] = WhisperModel(
                    model_path,
                    device="cpu",
                    compute_type=options.compute_type,
                )
            except Exception as error:
                if _contains_certificate_error(error):
                    raise RuntimeError(
                        "モデルのダウンロードに必要な証明書を確認できません。"
                        "社内ルート証明書をWindowsの信頼されたルート証明機関に登録するか、"
                        "SSL_CERT_FILEにCA証明書ファイルを指定してください。"
                    ) from error
                raise
        token.raise_if_cancelled()

        self._report(progress, ProgressStage.TRANSCRIBING, 0.0, "文字起こし中")
        raw_segments, info = self._models[model_key].transcribe(
            str(source),
            language=options.language,
            vad_filter=options.vad_filter,
        )
        duration = info.duration or media.duration_seconds
        segments: list[Segment] = []
        for raw_segment in raw_segments:
            token.raise_if_cancelled()
            segments.append(
                Segment(
                    start_seconds=raw_segment.start,
                    end_seconds=raw_segment.end,
                    text=raw_segment.text.strip(),
                )
            )
            fraction = min(raw_segment.end / duration, 1.0) if duration else None
            self._report(progress, ProgressStage.TRANSCRIBING, fraction, "文字起こし中")

        token.raise_if_cancelled()
        return Transcript(
            language=info.language,
            language_probability=info.language_probability,
            duration_seconds=duration,
            segments=tuple(segments),
            metadata={
                "model": options.model_name,
                "compute_type": options.compute_type,
                "audio_codec": media.audio_codec or "unknown",
            },
        )

    @staticmethod
    def _report(
        callback: ProgressCallback | None,
        stage: ProgressStage,
        fraction: float | None,
        message: str,
    ) -> None:
        if callback is not None:
            callback(ProgressEvent(stage=stage, fraction=fraction, message=message))


def _contains_certificate_error(error: BaseException) -> bool:
    current: BaseException | None = error
    while current is not None:
        if "CERTIFICATE_VERIFY_FAILED" in str(current).upper():
            return True
        current = current.__cause__ or current.__context__
    return False


def _resolve_model(
    model_name: str,
    progress: ProgressCallback | None,
    cancellation: CancellationToken,
) -> str:
    repository = MODEL_REPOSITORIES.get(model_name)
    if repository is None:
        raise ValueError(f"未対応のモデルです: {model_name}")
    truststore.inject_into_ssl()
    cache_dir = model_cache_dir()
    cache_dir.mkdir(parents=True, exist_ok=True)
    try:
        return str(
            snapshot_download(
                repository,
                cache_dir=cache_dir,
                local_files_only=True,
                allow_patterns=_MODEL_FILES,
            )
        )
    except LocalEntryNotFoundError:
        cancellation.raise_if_cancelled()

    return str(
        snapshot_download(
            repository,
            cache_dir=cache_dir,
            allow_patterns=_MODEL_FILES,
            tqdm_class=cast(Any, _progress_tqdm(progress, cancellation)),
        )
    )


def _progress_tqdm(
    progress: ProgressCallback | None,
    cancellation: CancellationToken,
) -> type[Any]:
    class DownloadProgress(tqdm):  # type: ignore[type-arg]
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            kwargs["file"] = _NULL_PROGRESS_STREAM
            super().__init__(*args, **kwargs)
            self._notify()

        def update(self, amount: float | None = 1) -> bool | None:
            cancellation.raise_if_cancelled()
            result = super().update(amount)
            self._notify()
            return result

        def _notify(self) -> None:
            if progress is None:
                return
            total = float(self.total) if self.total else 0.0
            fraction = min(float(self.n) / total, 1.0) if total else None
            description = getattr(self, "desc", None) or "モデルをダウンロードしています"
            progress(ProgressEvent(ProgressStage.DOWNLOADING_MODEL, fraction, description))

    return DownloadProgress
