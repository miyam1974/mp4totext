import json
import math
import statistics
from dataclasses import asdict, dataclass

from PySide6.QtCore import QSettings

from mp4totext.gui.i18n import Language

_HISTORY_KEY = "processing/history/v1"
_MAX_SAMPLES_PER_MODEL = 20


@dataclass(frozen=True, slots=True)
class ProcessingMetrics:
    model_name: str
    file_size_bytes: int
    elapsed_seconds: float


def load_history(settings: QSettings) -> tuple[ProcessingMetrics, ...]:
    raw = str(settings.value(_HISTORY_KEY, "", type=str))
    if not raw:
        return ()
    try:
        records = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return ()
    samples: list[ProcessingMetrics] = []
    if not isinstance(records, list):
        return ()
    for record in records:
        if not isinstance(record, dict):
            continue
        try:
            sample = ProcessingMetrics(
                model_name=str(record["model_name"]),
                file_size_bytes=int(record["file_size_bytes"]),
                elapsed_seconds=float(record["elapsed_seconds"]),
            )
        except (KeyError, TypeError, ValueError):
            continue
        if (
            sample.model_name
            and sample.file_size_bytes > 0
            and sample.elapsed_seconds > 0
            and math.isfinite(sample.elapsed_seconds)
        ):
            samples.append(sample)
    return tuple(samples)


def append_history(settings: QSettings, sample: ProcessingMetrics) -> None:
    samples = list(load_history(settings))
    samples.append(sample)
    retained: list[ProcessingMetrics] = []
    for model_name in dict.fromkeys(item.model_name for item in samples):
        model_samples = [item for item in samples if item.model_name == model_name]
        retained.extend(model_samples[-_MAX_SAMPLES_PER_MODEL:])
    settings.setValue(_HISTORY_KEY, json.dumps([asdict(item) for item in retained]))


def estimate_seconds(
    model_name: str,
    file_size_bytes: int,
    history: tuple[ProcessingMetrics, ...],
) -> float | None:
    seconds_per_byte = [
        sample.elapsed_seconds / sample.file_size_bytes
        for sample in history
        if sample.model_name == model_name and sample.file_size_bytes > 0
    ]
    if not seconds_per_byte or file_size_bytes <= 0:
        return None
    return statistics.median(seconds_per_byte) * file_size_bytes


def format_duration(seconds: float, language: Language = Language.JA) -> str:
    total_seconds = max(round(seconds), 0)
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if language is Language.EN:
        if hours:
            return f"{hours}h {minutes:02}m {seconds:02}s"
        if minutes:
            return f"{minutes}m {seconds:02}s"
        return f"{seconds}s"
    if hours:
        return f"{hours}時間{minutes:02}分{seconds:02}秒"
    if minutes:
        return f"{minutes}分{seconds:02}秒"
    return f"{seconds}秒"
