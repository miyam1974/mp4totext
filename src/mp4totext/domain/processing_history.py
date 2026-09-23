import math
import statistics
from dataclasses import dataclass

MAX_SAMPLES_PER_MODEL = 20


@dataclass(frozen=True, slots=True)
class ProcessingMetrics:
    model_name: str
    file_size_bytes: int
    elapsed_seconds: float

    @property
    def valid(self) -> bool:
        return (
            bool(self.model_name.strip())
            and self.file_size_bytes > 0
            and self.elapsed_seconds > 0
            and math.isfinite(self.elapsed_seconds)
        )


def retain_history(history: tuple[ProcessingMetrics, ...]) -> tuple[ProcessingMetrics, ...]:
    """Keep the latest valid samples per model, preserving chronological order."""
    counts: dict[str, int] = {}
    retained: list[ProcessingMetrics] = []
    for sample in reversed(history):
        count = counts.get(sample.model_name, 0)
        if sample.valid and count < MAX_SAMPLES_PER_MODEL:
            retained.append(sample)
            counts[sample.model_name] = count + 1
    return tuple(reversed(retained))


def estimate_rate(model_name: str, history: tuple[ProcessingMetrics, ...]) -> float | None:
    """Return the median seconds per byte for one model."""
    rates = [
        sample.elapsed_seconds / sample.file_size_bytes
        for sample in history
        if sample.model_name == model_name and sample.valid
    ]
    return statistics.median(rates) if rates else None


def estimate_seconds(
    model_name: str, file_size_bytes: int, history: tuple[ProcessingMetrics, ...],
) -> float | None:
    rate = estimate_rate(model_name, history)
    return rate * file_size_bytes if rate is not None and file_size_bytes > 0 else None
